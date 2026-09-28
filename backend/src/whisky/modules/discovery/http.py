"""Authenticated exploration plan HTTP adapter."""

import base64
import binascii
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanConflict, PlanCursor, PlanStore
from whisky.modules.identity.public import AccessSession, IdentityAccess
from whisky.platform.http_errors import PublicAPIError


class CreatePlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=128)
    conditions: ResearchConditions

    @field_validator("key")
    @classmethod
    def nonempty_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Command key must not be blank")
        return value


class PlanView(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )
    id: UUID
    conditions_revision: int
    conditions: ResearchConditions


class PlanListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=20, ge=1, le=50)
    cursor: str | None = Field(default=None, min_length=1, max_length=512)


class PlanListView(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    items: tuple[PlanView, ...]
    next_cursor: str | None


class CursorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    updated_at: AwareDatetime
    id: UUID


def plan_router(identity: IdentityAccess, store: PlanStore | None) -> APIRouter:
    routes = APIRouter(prefix="/api/v1")
    bearer = HTTPBearer(auto_error=False)

    def authenticate(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> AccessSession:
        return identity.authenticate(credentials.credentials if credentials else None)

    @routes.get("/plans", response_model=PlanListView)
    def list_plans(
        request: Request,
        query: Annotated[PlanListQuery, Query()],
        session: AccessSession = Depends(authenticate),
    ) -> PlanListView:
        if any(
            len(request.query_params.getlist(key)) > 1 for key in ("limit", "cursor")
        ):
            raise PublicAPIError(422, "INVALID_REQUEST")
        if store is None:
            raise PublicAPIError(503, "DISCOVERY_UNAVAILABLE")
        cursor = None
        if query.cursor is not None:
            try:
                payload = CursorPayload.model_validate_json(
                    base64.b64decode(query.cursor, altchars=b"-_", validate=True)
                )
            except (ValueError, binascii.Error):
                raise PublicAPIError(422, "INVALID_REQUEST") from None
            cursor = PlanCursor(payload.updated_at, payload.id)
        page = store.page(session.actor_id, query.limit, cursor)
        next_cursor = None
        if page.next_cursor is not None:
            payload = CursorPayload(
                updated_at=page.next_cursor.updated_at, id=page.next_cursor.id
            )
            next_cursor = base64.urlsafe_b64encode(
                payload.model_dump_json().encode()
            ).decode("ascii")
        return PlanListView(
            items=tuple(PlanView.model_validate(item) for item in page.items),
            next_cursor=next_cursor,
        )

    @routes.post("/plans", response_model=PlanView, status_code=201)
    def create_plan(
        request: CreatePlanInput, session: AccessSession = Depends(authenticate)
    ) -> PlanView:
        if store is None:
            raise PublicAPIError(503, "DISCOVERY_UNAVAILABLE")
        try:
            plan = store.create(
                session.actor_id, session.generation, request.key, request.conditions
            )
        except PlanConflict as error:
            code = str(error)
            status = {
                "IDEMPOTENCY_CONFLICT": 409,
                "IDENTITY_CHANGED": 403,
                "CATALOG_REFERENCE_NOT_FOUND": 404,
            }.get(code)
            if status is None:
                raise
            raise PublicAPIError(status, code) from None
        return PlanView.model_validate(plan)

    @routes.get("/plans/{plan_id}", response_model=PlanView)
    def read_plan(
        plan_id: UUID, session: AccessSession = Depends(authenticate)
    ) -> PlanView:
        if store is None:
            raise PublicAPIError(503, "DISCOVERY_UNAVAILABLE")
        plan = store.read(plan_id, session.actor_id)
        if plan is None:
            raise HTTPException(404, "NOT_FOUND")
        return PlanView.model_validate(plan)

    return routes
