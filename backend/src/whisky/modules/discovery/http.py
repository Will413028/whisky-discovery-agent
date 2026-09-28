"""Authenticated exploration plan HTTP adapter."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanConflict, PlanStore
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


def plan_router(identity: IdentityAccess, store: PlanStore | None) -> APIRouter:
    routes = APIRouter(prefix="/api/v1")
    bearer = HTTPBearer(auto_error=False)

    def authenticate(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> AccessSession:
        return identity.authenticate(credentials.credentials if credentials else None)

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
