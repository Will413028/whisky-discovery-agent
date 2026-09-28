"""Authenticated, read-only task observation HTTP adapter."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from whisky.modules.identity.public import AccessSession, IdentityAccess
from whisky.modules.research.observation import (
    ObservationPolicy,
    ObservationSource,
    ObserveInput,
    Observer,
)
from whisky.modules.research.store import ResearchStore
from whisky.modules.research.views import ResearchCommandView, TaskView
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


def observation_router(
    identity: IdentityAccess,
    source: ObservationSource | None,
    policy: ObservationPolicy = ObservationPolicy(),
    *,
    store: ResearchStore | None = None,
) -> APIRouter:
    routes = APIRouter()
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

    @routes.post("/agent/observe", response_class=StreamingResponse)
    async def observe(
        request: ObserveInput, session: AccessSession = Depends(authenticate)
    ) -> StreamingResponse:
        return await observer.response(request, session.actor_id, session.expires_at)

    return routes
