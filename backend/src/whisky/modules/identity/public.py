"""Public identity HTTP composition contract."""

from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from whisky.modules.identity.store import IdentityStore
from whisky.modules.identity.tokens import InvalidToken, TokenVerifier


class ActorView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID


@dataclass(frozen=True)
class AccessSession:
    actor_id: UUID
    expires_at: float
    generation: int


class IdentityAccess:
    """Public authentication and live actor eligibility contract."""

    def __init__(self, engine: Engine | None, verifier: TokenVerifier | None) -> None:
        self.store = IdentityStore(engine) if engine is not None else None
        self.verifier = verifier

    def is_active(self, actor_id: UUID) -> bool:
        if self.store is None:
            return False
        actor = self.store.read_actor(actor_id, actor_id)
        return actor is not None and actor.active

    def authenticate(self, token: str | None) -> AccessSession:
        if self.store is None or self.verifier is None:
            raise HTTPException(503, "IDENTITY_UNAVAILABLE")
        if token is None:
            raise HTTPException(
                401, "UNAUTHENTICATED", headers={"WWW-Authenticate": "Bearer"}
            )
        try:
            access = self.verifier.verify_access(token)
        except InvalidToken:
            raise HTTPException(
                401, "UNAUTHENTICATED", headers={"WWW-Authenticate": "Bearer"}
            ) from None
        actor = self.store.resolve(access.principal)
        assert actor is not None
        if not actor.active:
            raise HTTPException(403, "ACTOR_DISABLED")
        return AccessSession(actor.id, access.expires_at, actor.generation)


def router(engine: Engine | None, verifier: TokenVerifier | None) -> APIRouter:
    routes = APIRouter(prefix="/api/v1")
    access = IdentityAccess(engine, verifier)
    store = access.store
    bearer = HTTPBearer(auto_error=False)

    def current_actor(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> AccessSession:
        return access.authenticate(credentials.credentials if credentials else None)

    @routes.get("/me", response_model=ActorView)
    def me(actor: AccessSession = Depends(current_actor)) -> ActorView:
        return ActorView(id=actor.actor_id)

    @routes.get("/actors/{actor_id}", response_model=ActorView)
    def read_actor(
        actor_id: UUID, actor: AccessSession = Depends(current_actor)
    ) -> ActorView:
        assert store is not None
        found = store.read_actor(actor_id, actor.actor_id)
        if found is None:
            raise HTTPException(404, "NOT_FOUND")
        return ActorView(id=found.id)

    return routes
