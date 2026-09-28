"""Public identity HTTP composition contract."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from whisky.modules.identity.store import Actor, IdentityStore
from whisky.modules.identity.tokens import InvalidToken, TokenVerifier


class ActorView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID


def router(engine: Engine | None, verifier: TokenVerifier | None) -> APIRouter:
    routes = APIRouter(prefix="/api/v1")
    store = IdentityStore(engine) if engine is not None else None
    bearer = HTTPBearer(auto_error=False)

    def current_actor(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> Actor:
        if store is None or verifier is None:
            raise HTTPException(503, "IDENTITY_UNAVAILABLE")
        if credentials is None:
            raise HTTPException(
                401, "UNAUTHENTICATED", headers={"WWW-Authenticate": "Bearer"}
            )
        try:
            principal = verifier.verify(credentials.credentials)
        except InvalidToken:
            raise HTTPException(
                401, "UNAUTHENTICATED", headers={"WWW-Authenticate": "Bearer"}
            ) from None
        actor = store.resolve(principal)
        assert actor is not None
        if not actor.active:
            raise HTTPException(403, "ACTOR_DISABLED")
        return actor

    @routes.get("/me", response_model=ActorView)
    def me(actor: Actor = Depends(current_actor)) -> ActorView:
        return ActorView(id=actor.id)

    @routes.get("/actors/{actor_id}", response_model=ActorView)
    def read_actor(actor_id: UUID, actor: Actor = Depends(current_actor)) -> ActorView:
        assert store is not None
        found = store.read_actor(actor_id, actor.id)
        if found is None:
            raise HTTPException(404, "NOT_FOUND")
        return ActorView(id=found.id)

    return routes
