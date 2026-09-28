"""Public identity HTTP composition contract."""

from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, Engine, select

from whisky.modules.identity.store import IdentityStore, users
from whisky.modules.identity.tokens import InvalidToken, TokenVerifier


class ActorView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID


@dataclass(frozen=True)
class AccessSession:
    actor_id: UUID
    expires_at: float
    generation: int


def actor_generation(
    connection: Connection, actor_id: UUID, *, lock: bool = False
) -> int | None:
    """Join a caller's transaction without exposing identity tables to modules.

    Mutation callers lock identity before their own command/aggregate rows.
    """
    query = select(users.c.generation).where(
        users.c.id == actor_id, users.c.active.is_(True)
    )
    if lock:
        query = query.with_for_update()
    value = connection.scalar(query)
    return int(value) if value is not None else None


def control_actor_state(
    connection: Connection, actor_id: UUID, *, lock: bool = False
) -> tuple[int, bool] | None:
    """Control commands must also reconcile a now-disabled actor."""
    query = select(users.c.generation, users.c.active).where(users.c.id == actor_id)
    if lock:
        query = query.with_for_update()
    row = connection.execute(query).first()
    return (int(row.generation), bool(row.active)) if row is not None else None


def disable_actor(connection: Connection, actor_id: UUID, generation: int) -> None:
    """Advance identity generation as the final step of an actor delete effect."""
    from sqlalchemy import update

    changed = connection.execute(
        update(users)
        .where(
            users.c.id == actor_id,
            users.c.generation == generation,
            users.c.active.is_(True),
        )
        .values(active=False, generation=generation + 1)
    )
    if changed.rowcount != 1:
        raise ValueError("IDENTITY_CHANGED")


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

    def authenticate_control_reconciliation(self, token: str | None) -> AccessSession:
        """A disabled actor may read/retry its original delete receipt only."""
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
        actor = self.store.lookup(access.principal)
        if actor is None:
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
