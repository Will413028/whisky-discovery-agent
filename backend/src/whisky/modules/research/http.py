"""Authenticated, read-only task observation HTTP adapter."""

import base64
import binascii
from typing import Annotated, Literal
from uuid import UUID

from ag_ui.core import RunAgentInput
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, Field, field_validator
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response, StreamingResponse

from whisky.modules.identity.public import AccessSession, IdentityAccess
from whisky.modules.research.acceptance import AcceptResearch
from whisky.modules.research.answer import AnswerResearch
from whisky.modules.research.commands import parse_resume, parse_start
from whisky.modules.research.comparison_views_v4 import ComparisonReportViewV4
from whisky.modules.research.contracts import AnswerInput
from whisky.modules.research.db_observation import DBObservationSource
from whisky.modules.research.inputs_v4 import parse_start_v4
from whisky.modules.research.observation import (
    ObservationPolicy,
    ObservationSource,
    ObserveInput,
    Observer,
)
from whisky.modules.research.proposal_view_v4 import PreferenceProposalViewV4
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.restart_context_v4 import (
    RestartContextViewV4,
    read_restart_context_v4,
)
from whisky.modules.research.store import (
    ResearchConflict,
    ResearchStore,
    TaskHistoryCursor,
)
from whisky.modules.research.views import (
    ReportView,
    ResearchCommandView,
    TaskHistoryView,
    TaskView,
    ViewModel,
)
from whisky.platform.http_errors import PublicAPIError


class TaskHistoryQuery(ViewModel):
    limit: int = Field(default=20, ge=1, le=50)
    cursor: str | None = Field(default=None, min_length=1, max_length=512)


class TaskHistoryCursorPayload(ViewModel):
    version: Literal[1] = 1
    created_at: AwareDatetime
    id: UUID


class AuthorizedSource:
    def __init__(
        self, identity: IdentityAccess, source: ObservationSource | None
    ) -> None:
        self.identity = identity
        self.source = source

    async def read(self, request: ObserveInput, owner: UUID) -> TaskView | None:
        if not await run_in_threadpool(self.identity.is_active, owner):
            return None
        if self.source is None:
            raise HTTPException(503, "OBSERVATION_UNAVAILABLE")
        return await self.source.read(request, owner)

    async def outcome(self, request: ObserveInput, owner: UUID) -> dict | None:
        if not await run_in_threadpool(self.identity.is_active, owner):
            return None
        if self.source is None:
            raise HTTPException(503, "OBSERVATION_UNAVAILABLE")
        return await self.source.outcome(request, owner)

    async def report(self, report_id: UUID, owner: UUID) -> ReportView | None:
        if not await run_in_threadpool(self.identity.is_active, owner):
            return None
        if self.source is None:
            return None
        return await self.source.report(report_id, owner)


class AnswerRequest(ViewModel):
    key: str = Field(min_length=1, max_length=128)
    conditions_revision: int = Field(ge=1)
    waiting_version: int = Field(ge=1)
    answer: str = Field(min_length=1, max_length=160)

    @field_validator("key", "answer")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Answer command fields cannot be blank")
        return value


def observation_router(
    identity: IdentityAccess,
    source: ObservationSource | None,
    policy: ObservationPolicy = ObservationPolicy(),
    *,
    store: ResearchStore | None = None,
    acceptance: AcceptResearch | None = None,
    answers: AnswerResearch | None = None,
    reports: ReportStore | None = None,
) -> APIRouter:
    routes = APIRouter()
    if source is None and store is not None:
        source = DBObservationSource(store, reports)
    observer = Observer(AuthorizedSource(identity, source), policy)
    bearer = HTTPBearer(auto_error=False)

    def authenticate(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> AccessSession:
        return identity.authenticate(credentials.credentials if credentials else None)

    @routes.get("/api/v1/plans/{plan_id}/tasks", response_model=TaskHistoryView)
    def task_history(
        plan_id: UUID,
        request: Request,
        query: Annotated[TaskHistoryQuery, Query()],
        session: AccessSession = Depends(authenticate),
    ) -> TaskHistoryView:
        if any(
            len(request.query_params.getlist(key)) > 1 for key in ("limit", "cursor")
        ):
            raise PublicAPIError(422, "INVALID_REQUEST")
        if store is None:
            raise PublicAPIError(503, "RESEARCH_UNAVAILABLE")
        cursor = None
        if query.cursor is not None:
            try:
                payload = TaskHistoryCursorPayload.model_validate_json(
                    base64.b64decode(query.cursor, altchars=b"-_", validate=True)
                )
            except (ValueError, binascii.Error):
                raise PublicAPIError(422, "INVALID_REQUEST") from None
            cursor = TaskHistoryCursor(payload.created_at, payload.id)
        page = store.history(plan_id, session.actor_id, query.limit, cursor)
        if page is None:
            raise HTTPException(404, "NOT_FOUND")
        next_cursor = None
        if page.next_cursor is not None:
            payload = TaskHistoryCursorPayload(
                created_at=page.next_cursor.created_at, id=page.next_cursor.id
            )
            next_cursor = base64.urlsafe_b64encode(
                payload.model_dump_json().encode()
            ).decode("ascii")
        return TaskHistoryView(items=page.items, next_cursor=next_cursor)

    @routes.get(
        "/api/v1/plans/{plan_id}/tasks/{task_id}/restart-context",
        response_model=RestartContextViewV4,
    )
    def read_restart_context(
        plan_id: UUID,
        task_id: UUID,
        session: AccessSession = Depends(authenticate),
    ) -> RestartContextViewV4:
        if store is None:
            raise PublicAPIError(503, "RESEARCH_UNAVAILABLE")
        view = read_restart_context_v4(store.engine, session.actor_id, plan_id, task_id)
        if view is None:
            raise HTTPException(404, "NOT_FOUND")
        return view

    @routes.get("/api/v1/tasks", response_model=tuple[TaskView, ...])
    def list_open_tasks(
        session: AccessSession = Depends(authenticate),
    ) -> tuple[TaskView, ...]:
        if store is None:
            raise PublicAPIError(503, "RESEARCH_UNAVAILABLE")
        return store.list_open(session.actor_id)

    @routes.get("/api/v1/tasks/{task_id}", response_model=TaskView)
    def read_task(
        task_id: UUID, session: AccessSession = Depends(authenticate)
    ) -> TaskView:
        if store is None:
            raise PublicAPIError(503, "RESEARCH_UNAVAILABLE")
        view = store.task(task_id, session.actor_id)
        if view is None:
            raise HTTPException(404, "NOT_FOUND")
        return view

    @routes.get(
        "/api/v1/tasks/{task_id}/preference-proposal",
        response_model=PreferenceProposalViewV4,
    )
    def read_preference_proposal(
        task_id: UUID, session: AccessSession = Depends(authenticate)
    ) -> PreferenceProposalViewV4:
        if store is None:
            raise PublicAPIError(503, "RESEARCH_UNAVAILABLE")
        view = store.preference_proposal(task_id, session.actor_id)
        if view is None:
            raise HTTPException(404, "NOT_FOUND")
        return view

    @routes.get("/api/v1/reports/{report_id}", response_model=ReportView)
    def read_report(
        report_id: UUID, session: AccessSession = Depends(authenticate)
    ) -> ReportView:
        if reports is None:
            raise PublicAPIError(503, "RESEARCH_UNAVAILABLE")
        view = reports.read(session.actor_id, report_id)
        if view is None:
            raise HTTPException(404, "NOT_FOUND")
        return view

    @routes.get(
        "/api/v1/reports/{report_id}/comparison",
        response_model=ComparisonReportViewV4,
    )
    def read_comparison(
        report_id: UUID, session: AccessSession = Depends(authenticate)
    ) -> ComparisonReportViewV4:
        if reports is None:
            raise PublicAPIError(503, "RESEARCH_UNAVAILABLE")
        view = reports.read_comparison_v4(session.actor_id, report_id)
        if view is None:
            raise HTTPException(404, "NOT_FOUND")
        return view

    @routes.get(
        "/api/v1/commands/{command_id}",
        response_model=ResearchCommandView,
        response_model_exclude_none=True,
    )
    def read_command(
        command_id: UUID, session: AccessSession = Depends(authenticate)
    ) -> ResearchCommandView:
        if store is None:
            raise PublicAPIError(503, "RESEARCH_UNAVAILABLE")
        view = store.command(command_id, session.actor_id)
        if view is None:
            raise HTTPException(404, "NOT_FOUND")
        return view

    @routes.post(
        "/api/v1/tasks/{task_id}/clarifications/{question_id}/answer",
        response_model=ResearchCommandView,
        response_model_exclude_none=True,
    )
    async def answer_question(
        task_id: UUID,
        question_id: UUID,
        body: AnswerRequest,
        response: Response,
        session: AccessSession = Depends(authenticate),
    ) -> ResearchCommandView:
        if answers is None:
            raise PublicAPIError(503, "RESEARCH_UNAVAILABLE")
        try:
            result = await answers.execute(
                session.actor_id,
                session.generation,
                AnswerInput(
                    task_id,
                    question_id,
                    body.waiting_version,
                    body.conditions_revision,
                    body.key,
                    body.answer,
                ),
            )
        except ResearchConflict as error:
            code = str(error)
            status = {
                "NOT_FOUND": 404,
                "IDENTITY_CHANGED": 403,
                "IDEMPOTENCY_CONFLICT": 409,
                "REVISION_CONFLICT": 409,
                "QUESTION_CLOSED": 409,
                "QUESTION_EXPIRED": 409,
                "TURN_CONFLICT": 409,
                "INVALID_ANSWER": 422,
            }.get(code)
            if status is None:
                raise
            raise PublicAPIError(status, code) from None
        if result.acceptance == "rejected":
            raise PublicAPIError(409, result.code or "QUESTION_CLOSED")
        if result.acceptance == "acceptance_pending":
            response.status_code = 202
        return ResearchCommandView(
            id=result.command_id,
            task_id=result.task_id,
            scope="research.answer",
            acceptance=result.acceptance,
        )

    @routes.post("/agent", response_class=StreamingResponse)
    async def start(
        request: RunAgentInput, session: AccessSession = Depends(authenticate)
    ) -> StreamingResponse:
        if request.resume:
            try:
                answer_turn = parse_resume(request)
            except ValueError:
                raise PublicAPIError(422, "INVALID_REQUEST") from None
            if answers is None:
                raise PublicAPIError(503, "RESEARCH_UNAVAILABLE")
            try:
                result = await answers.execute(
                    session.actor_id, session.generation, answer_turn.command
                )
            except ResearchConflict as error:
                code = str(error)
                status = {
                    "NOT_FOUND": 404,
                    "IDENTITY_CHANGED": 403,
                    "IDEMPOTENCY_CONFLICT": 409,
                    "REVISION_CONFLICT": 409,
                    "TASK_NOT_WRITABLE": 409,
                    "QUESTION_CLOSED": 409,
                    "QUESTION_EXPIRED": 409,
                    "TURN_CONFLICT": 409,
                    "INVALID_ANSWER": 422,
                }.get(code)
                if status is None:
                    raise
                raise PublicAPIError(status, code) from None
            if result.acceptance == "rejected":
                raise PublicAPIError(409, result.code or "QUESTION_CLOSED")
            response = await observer.response(
                ObserveInput(
                    task_id=result.task_id,
                    run_id=answer_turn.run_id,
                    conditions_revision=answer_turn.command.conditions_revision,
                ),
                session.actor_id,
                session.expires_at,
            )
            response.headers["X-Command-Id"] = str(result.command_id)
            return response
        try:
            start_turn = (
                parse_start_v4(request)
                if request.forwarded_props.get("type") == "start_v4"
                else parse_start(request)
            )
        except ValueError:
            raise PublicAPIError(422, "INVALID_REQUEST") from None
        if acceptance is None:
            raise PublicAPIError(503, "RESEARCH_UNAVAILABLE")
        try:
            receipt = await acceptance.execute_turn(
                session.actor_id, session.generation, start_turn
            )
        except ResearchConflict as error:
            code = str(error)
            status = {
                "NOT_FOUND": 404,
                "IDENTITY_CHANGED": 403,
                "IDEMPOTENCY_CONFLICT": 409,
                "REVISION_CONFLICT": 409,
                "TASK_NOT_WRITABLE": 409,
                "TURN_CONFLICT": 409,
            }.get(code)
            if status is None:
                raise
            raise PublicAPIError(status, code) from None
        response = await observer.response(
            ObserveInput(
                task_id=receipt.task_id,
                run_id=start_turn.run_id,
                conditions_revision=start_turn.command.conditions_revision,
            ),
            session.actor_id,
            session.expires_at,
        )
        response.headers["X-Command-Id"] = str(receipt.id)
        return response

    @routes.post("/agent/observe", response_class=StreamingResponse)
    async def observe(
        request: ObserveInput, session: AccessSession = Depends(authenticate)
    ) -> StreamingResponse:
        return await observer.response(request, session.actor_id, session.expires_at)

    return routes
