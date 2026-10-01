"""Private library HTTP adapter; ordinary saves do not execute an Agent."""

import base64
import binascii
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, Field

from whisky.modules.catalog.public import taiwan_date
from whisky.modules.identity.public import AccessSession, IdentityAccess
from whisky.modules.library.contracts import (
    BottleFeedbackListViewV1,
    BottleFeedbackViewV1,
    ConclusionContextViewV1,
    ConclusionListViewV1,
    ConclusionRevisitViewV1,
    ConclusionViewV1,
    LibraryModel,
    SaveBottleFeedbackV1,
    SaveConclusionV1,
)
from whisky.modules.library.store import ConclusionCursor, LibraryConflict, LibraryStore
from whisky.platform.http_errors import PublicAPIError


class ConclusionsQuery(LibraryModel):
    plan_id: UUID
    limit: int = Field(default=20, ge=1, le=50)
    cursor: str | None = Field(default=None, min_length=1, max_length=512)


class ConclusionCursorPayload(LibraryModel):
    version: Literal[1] = 1
    updated_at: AwareDatetime
    id: UUID


class FeedbackQuery(LibraryModel):
    limit: int = Field(default=20, ge=1, le=50)
    cursor: str | None = Field(default=None, min_length=1, max_length=512)


def read_cursor(value: str | None) -> ConclusionCursor | None:
    if value is None:
        return None
    try:
        payload = ConclusionCursorPayload.model_validate_json(
            base64.b64decode(value, altchars=b"-_", validate=True)
        )
    except (ValueError, binascii.Error):
        raise PublicAPIError(422, "INVALID_REQUEST") from None
    return ConclusionCursor(payload.updated_at, payload.id)


def write_cursor(value: ConclusionCursor | None) -> str | None:
    if value is None:
        return None
    payload = ConclusionCursorPayload(updated_at=value.updated_at, id=value.id)
    return base64.urlsafe_b64encode(payload.model_dump_json().encode()).decode()


def library_router(identity: IdentityAccess, store: LibraryStore | None) -> APIRouter:
    routes = APIRouter(prefix="/api/v1/library")
    bearer = HTTPBearer(auto_error=False)

    def authenticate(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> AccessSession:
        return identity.authenticate(credentials.credentials if credentials else None)

    @routes.post("/feedback", response_model=BottleFeedbackViewV1, status_code=201)
    def save_feedback(
        command: SaveBottleFeedbackV1, session: AccessSession = Depends(authenticate)
    ) -> BottleFeedbackViewV1:
        if store is None:
            raise PublicAPIError(503, "LIBRARY_UNAVAILABLE")
        try:
            return store.save_bottle_feedback(
                session.actor_id, session.generation, command
            )
        except LibraryConflict as error:
            code = str(error)
            status = (
                404
                if code == "NOT_FOUND"
                else 409
                if code
                in {"REVISION_CONFLICT", "IDEMPOTENCY_CONFLICT", "IDENTITY_CHANGED"}
                else 422
            )
            raise PublicAPIError(status, code) from None

    @routes.get("/feedback/{version}", response_model=BottleFeedbackViewV1)
    def read_feedback(
        version: UUID, session: AccessSession = Depends(authenticate)
    ) -> BottleFeedbackViewV1:
        if store is None:
            raise PublicAPIError(503, "LIBRARY_UNAVAILABLE")
        saved = store.read_bottle_feedback(session.actor_id, version)
        if saved is None:
            raise PublicAPIError(404, "NOT_FOUND")
        return saved

    @routes.get("/feedback", response_model=BottleFeedbackListViewV1)
    def list_feedback(
        request: Request,
        query: Annotated[FeedbackQuery, Query()],
        session: AccessSession = Depends(authenticate),
    ) -> BottleFeedbackListViewV1:
        if any(
            len(request.query_params.getlist(key)) > 1 for key in ("limit", "cursor")
        ):
            raise PublicAPIError(422, "INVALID_REQUEST")
        if store is None:
            raise PublicAPIError(503, "LIBRARY_UNAVAILABLE")
        page = store.page_bottle_feedback(
            session.actor_id, query.limit, read_cursor(query.cursor)
        )
        return BottleFeedbackListViewV1(
            items=page.items, next_cursor=write_cursor(page.next_cursor)
        )

    @routes.get(
        "/reports/{report_id}/conclusion-context",
        response_model=ConclusionContextViewV1,
    )
    def conclusion_context(
        report_id: UUID, session: AccessSession = Depends(authenticate)
    ) -> ConclusionContextViewV1:
        if store is None:
            raise PublicAPIError(503, "LIBRARY_UNAVAILABLE")
        context = store.conclusion_context(session.actor_id, report_id)
        if context is None:
            raise PublicAPIError(404, "NOT_FOUND")
        return context

    @routes.get("/conclusions", response_model=ConclusionListViewV1)
    def list_conclusions(
        request: Request,
        query: Annotated[ConclusionsQuery, Query()],
        session: AccessSession = Depends(authenticate),
    ) -> ConclusionListViewV1:
        if any(
            len(request.query_params.getlist(key)) > 1
            for key in ("planId", "limit", "cursor")
        ):
            raise PublicAPIError(422, "INVALID_REQUEST")
        if store is None:
            raise PublicAPIError(503, "LIBRARY_UNAVAILABLE")
        cursor = read_cursor(query.cursor)
        try:
            page = store.page_conclusions(
                session.actor_id, query.plan_id, query.limit, cursor
            )
        except LibraryConflict as error:
            raise PublicAPIError(404, str(error)) from None
        return ConclusionListViewV1(
            plan_id=query.plan_id,
            items=page.items,
            next_cursor=write_cursor(page.next_cursor),
        )

    @routes.post("/conclusions", response_model=ConclusionViewV1, status_code=201)
    def save_conclusion(
        command: SaveConclusionV1, session: AccessSession = Depends(authenticate)
    ) -> ConclusionViewV1:
        if store is None:
            raise PublicAPIError(503, "LIBRARY_UNAVAILABLE")
        try:
            return store.save_conclusion(session.actor_id, session.generation, command)
        except LibraryConflict as error:
            code = str(error)
            status = (
                404
                if code == "NOT_FOUND"
                else 409
                if code
                in {"REVISION_CONFLICT", "IDEMPOTENCY_CONFLICT", "IDENTITY_CHANGED"}
                else 422
            )
            raise PublicAPIError(status, code) from None

    @routes.get("/conclusions/{conclusion_id}", response_model=ConclusionViewV1)
    def read_conclusion(
        conclusion_id: UUID, session: AccessSession = Depends(authenticate)
    ) -> ConclusionViewV1:
        if store is None:
            raise PublicAPIError(503, "LIBRARY_UNAVAILABLE")
        saved = store.read_conclusion(session.actor_id, conclusion_id)
        if saved is None:
            raise PublicAPIError(404, "NOT_FOUND")
        return saved

    @routes.get(
        "/conclusions/{conclusion_id}/revisit", response_model=ConclusionRevisitViewV1
    )
    def revisit_conclusion(
        conclusion_id: UUID, session: AccessSession = Depends(authenticate)
    ) -> ConclusionRevisitViewV1:
        if store is None:
            raise PublicAPIError(503, "LIBRARY_UNAVAILABLE")
        try:
            current = store.revisit_conclusion(
                session.actor_id, conclusion_id, taiwan_date(datetime.now(UTC))
            )
        except LibraryConflict:
            raise PublicAPIError(503, "CATALOG_UNAVAILABLE") from None
        if current is None:
            raise PublicAPIError(404, "NOT_FOUND")
        return current

    return routes
