"""Authenticated, read-only task observation HTTP adapter."""

from uuid import UUID

from ag_ui.core import RunAgentInput
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from whisky.modules.identity.public import AccessSession, IdentityAccess
from whisky.modules.research.acceptance import AcceptResearch
from whisky.modules.research.commands import parse_start
from whisky.modules.research.db_observation import DBObservationSource
from whisky.modules.research.observation import (
    ObservationPolicy,
    ObservationSource,
    ObserveInput,
    Observer,
)
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.store import ResearchConflict, ResearchStore
from whisky.modules.research.views import ReportView, ResearchCommandView, TaskView
from whisky.platform.http_errors import PublicAPIError


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

    async def report(self, report_id: UUID, owner: UUID) -> ReportView | None:
        if not await run_in_threadpool(self.identity.is_active, owner):
            return None
        if self.source is None:
            return None
        return await self.source.report(report_id, owner)


def observation_router(
    identity: IdentityAccess,
    source: ObservationSource | None,
    policy: ObservationPolicy = ObservationPolicy(),
    *,
    store: ResearchStore | None = None,
    acceptance: AcceptResearch | None = None,
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

    @routes.get("/api/v1/commands/{command_id}", response_model=ResearchCommandView)
    def read_command(
        command_id: UUID, session: AccessSession = Depends(authenticate)
    ) -> ResearchCommandView:
        if store is None:
            raise PublicAPIError(503, "RESEARCH_UNAVAILABLE")
        view = store.command(command_id, session.actor_id)
        if view is None:
            raise HTTPException(404, "NOT_FOUND")
        return view

    @routes.post("/agent", response_class=StreamingResponse)
    async def start(
        request: RunAgentInput, session: AccessSession = Depends(authenticate)
    ) -> StreamingResponse:
        try:
            turn = parse_start(request)
        except ValueError:
            raise PublicAPIError(422, "INVALID_REQUEST") from None
        if acceptance is None:
            raise PublicAPIError(503, "RESEARCH_UNAVAILABLE")
        try:
            receipt = await acceptance.execute_turn(
                session.actor_id, session.generation, turn
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
                run_id=turn.run_id,
                conditions_revision=turn.command.conditions_revision,
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
