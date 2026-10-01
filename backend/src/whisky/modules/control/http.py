"""Authenticated typed control commands and recoverable result receipts."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel
from starlette.responses import Response

from whisky.modules.control.service import ControlController
from whisky.modules.control.store import (
    ControlConflict,
    ControlKind,
    ControlReceipt,
    ControlStore,
)
from whisky.modules.discovery.public import (
    ConditionPatch,
    ResearchConditions,
    apply_condition_patch,
)
from whisky.modules.identity.public import AccessSession, IdentityAccess
from whisky.platform.http_errors import PublicAPIError


class ControlView(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )
    id: UUID
    kind: ControlKind
    target_id: UUID
    status: Literal[
        "pending",
        "intent_confirmed",
        "effect_applied",
        "effect_rejected",
        "completed",
        "rejected",
    ]
    result: dict[str, str] | None


class KeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: UUID

    @field_validator("key")
    @classmethod
    def opaque_key(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("Control key must be a UUIDv4")
        return value


class ChangeConditionsRequest(KeyRequest):
    model_config = ConfigDict(
        extra="forbid", alias_generator=to_camel, populate_by_name=True
    )
    expected_revision: int = Field(ge=1)
    conditions: ResearchConditions


class PatchConditionsRequest(KeyRequest):
    model_config = ConfigDict(
        extra="forbid", alias_generator=to_camel, populate_by_name=True
    )
    expected_revision: int = Field(ge=1)
    base_conditions: ResearchConditions
    patch: ConditionPatch


def control_router(
    identity: IdentityAccess,
    store: ControlStore | None,
    controller: ControlController | None,
) -> APIRouter:
    routes = APIRouter(prefix="/api/v1")
    bearer = HTTPBearer(auto_error=False)

    def active_actor(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> AccessSession:
        return identity.authenticate(credentials.credentials if credentials else None)

    def reconciling_actor(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> AccessSession:
        return identity.authenticate_control_reconciliation(
            credentials.credentials if credentials else None
        )

    async def issue(
        actor: AccessSession,
        kind: ControlKind,
        target: UUID,
        key: str,
        response: Response,
        *,
        expected_revision: int = 0,
        conditions: ResearchConditions | None = None,
        base_conditions: ResearchConditions | None = None,
    ) -> ControlView:
        if controller is None:
            raise PublicAPIError(503, "CONTROL_UNAVAILABLE")
        try:
            receipt = await controller.execute(
                actor.actor_id,
                actor.generation,
                kind,
                target,
                key,
                expected_revision=expected_revision,
                conditions=conditions,
                base_conditions=base_conditions,
            )
        except ControlConflict as error:
            code = str(error)
            status = {
                "NOT_FOUND": 404,
                "IDENTITY_CHANGED": 403,
                "REVISION_CONFLICT": 409,
                "IDEMPOTENCY_CONFLICT": 409,
                "BASE_CONDITIONS_CONFLICT": 409,
            }.get(code)
            if status is None:
                raise
            raise PublicAPIError(status, code) from None
        response.status_code = (
            200 if receipt.status in {"completed", "rejected"} else 202
        )
        return ControlView.model_validate(receipt)

    @routes.post("/tasks/{task_id}/cancel", response_model=ControlView)
    async def cancel_task(
        task_id: UUID,
        body: KeyRequest,
        response: Response,
        actor: AccessSession = Depends(active_actor),
    ) -> ControlView:
        return await issue(actor, "task.cancel", task_id, str(body.key), response)

    @routes.post("/plans/{plan_id}/conditions", response_model=ControlView)
    async def change_plan_conditions(
        plan_id: UUID,
        body: ChangeConditionsRequest,
        response: Response,
        actor: AccessSession = Depends(active_actor),
    ) -> ControlView:
        return await issue(
            actor,
            "plan.change_conditions",
            plan_id,
            str(body.key),
            response,
            expected_revision=body.expected_revision,
            conditions=body.conditions,
        )

    @routes.post("/plans/{plan_id}/conditions/patch", response_model=ControlView)
    async def patch_plan_conditions(
        plan_id: UUID,
        body: PatchConditionsRequest,
        response: Response,
        actor: AccessSession = Depends(active_actor),
    ) -> ControlView:
        try:
            conditions = apply_condition_patch(
                body.base_conditions, body.patch.model_dump(exclude_unset=True)
            )
        except ValueError:
            raise PublicAPIError(422, "INVALID_CONDITION_PATCH") from None
        return await issue(
            actor,
            "plan.change_conditions",
            plan_id,
            str(body.key),
            response,
            expected_revision=body.expected_revision,
            conditions=conditions,
            base_conditions=body.base_conditions,
        )

    @routes.post("/plans/{plan_id}/delete", response_model=ControlView)
    async def delete_plan(
        plan_id: UUID,
        body: KeyRequest,
        response: Response,
        actor: AccessSession = Depends(active_actor),
    ) -> ControlView:
        return await issue(actor, "plan.delete", plan_id, str(body.key), response)

    @routes.post("/me/delete", response_model=ControlView)
    async def delete_actor(
        body: KeyRequest,
        response: Response,
        actor: AccessSession = Depends(reconciling_actor),
    ) -> ControlView:
        return await issue(
            actor, "actor.delete", actor.actor_id, str(body.key), response
        )

    @routes.get("/control-commands/{command_id}", response_model=ControlView)
    def read_control(
        command_id: UUID, actor: AccessSession = Depends(reconciling_actor)
    ) -> ControlView:
        if store is None:
            raise PublicAPIError(503, "CONTROL_UNAVAILABLE")
        receipt: ControlReceipt | None = store.read(command_id, actor.actor_id)
        if receipt is None:
            raise HTTPException(404, "NOT_FOUND")
        if not identity.is_active(actor.actor_id) and (
            receipt.kind != "actor.delete" or receipt.generation + 1 != actor.generation
        ):
            raise HTTPException(404, "NOT_FOUND")
        return ControlView.model_validate(receipt)

    return routes
