"""HTTP process entry point."""

import argparse
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import uvicorn
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from whisky.bootstrap.errors import ErrorView, error_response
from whisky.bootstrap.settings import Settings
from whisky.modules.identity.public import IdentityAccess, router
from whisky.modules.identity.tokens import TokenVerifier
from whisky.modules.research.http import observation_router as research_router


def configured_app(settings: Settings | None) -> FastAPI:
    if settings is None:
        return create_app()
    engine = create_engine(
        settings.database_url, pool_pre_ping=True, pool_size=5, max_overflow=0
    )
    verifier = TokenVerifier(
        settings.issuer, settings.audience, settings.issuer + ".well-known/jwks.json"
    )
    app = create_app(
        router(engine, verifier),
        research_router(IdentityAccess(engine, verifier), None),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            engine.dispose()

    app.router.lifespan_context = lifespan
    return app


def create_app(
    identity_router: APIRouter | None = None,
    observation_router: APIRouter | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Whisky Discovery Agent",
        responses={
            status: {"model": ErrorView} for status in (401, 403, 404, 422, 429, 503)
        },
    )
    app.include_router(
        identity_router if identity_router is not None else router(None, None)
    )
    app.include_router(
        observation_router
        if observation_router is not None
        else research_router(IdentityAccess(None, None), None)
    )

    @app.middleware("http")
    async def private_no_store(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request.state.request_id = uuid4()
        try:
            response = await call_next(request)
        except SQLAlchemyError:
            response = error_response(
                503, "DATABASE_UNAVAILABLE", request.state.request_id
            )
        if request.url.path.startswith(("/api/", "/agent/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> Response:
        codes = {
            401: "UNAUTHENTICATED",
            403: "ACTOR_DISABLED",
            404: "NOT_FOUND",
            429: "OBSERVATION_LIMIT",
            503: "IDENTITY_UNAVAILABLE",
        }
        return error_response(
            error.status_code,
            codes.get(error.status_code, "REQUEST_REJECTED"),
            request.state.request_id,
            error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, _error: RequestValidationError
    ) -> Response:
        return error_response(422, "INVALID_REQUEST", request.state.request_id)

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        """Process liveness only; does not claim DB or worker readiness."""
        return {"status": "ok"}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8417)
    args = parser.parse_args()
    uvicorn.run(
        configured_app(Settings.from_environment(os.environ)),
        host=args.host,
        port=args.port,
    )
