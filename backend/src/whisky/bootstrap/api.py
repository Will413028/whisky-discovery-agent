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
from whisky.modules.catalog.http import catalog_router as make_catalog_router
from whisky.modules.control.http import control_router as make_control_router
from whisky.modules.control.service import ControlController
from whisky.modules.control.store import ControlStore
from whisky.modules.control.temporal_start import ConnectingTemporalControlStarter
from whisky.modules.discovery.http import plan_router as discovery_router
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.public import IdentityAccess, router
from whisky.modules.identity.tokens import TokenVerifier
from whisky.modules.library.http import library_router as make_library_router
from whisky.modules.library.store import LibraryStore
from whisky.modules.research.acceptance import AcceptResearch
from whisky.modules.research.answer import AnswerResearch
from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.http import observation_router as research_router
from whisky.modules.research.observation import ObservationSource
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.store import ResearchStore
from whisky.modules.research.temporal_start import ConnectingTemporalResearchStarter
from whisky.platform.http_errors import PublicAPIError
from whisky.platform.recovery_gate import assert_recovery_ready, install_recovery_gate


def configured_app(
    settings: Settings | None, source: ObservationSource | None = None
) -> FastAPI:
    if settings is None:
        return create_app()
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=0,
        pool_timeout=5,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
    )
    if settings.recovery_required:
        install_recovery_gate(engine)
    verifier = TokenVerifier(
        settings.issuer, settings.audience, settings.issuer + ".well-known/jwks.json"
    )
    research_store = ResearchStore(engine)
    acceptance = None
    answers = None
    if settings.temporal is not None:
        temporal_client = ConnectingTemporalResearchStarter(
            settings.temporal.address,
            settings.temporal.namespace,
            settings.temporal.task_queue,
            workflow_type_for_task=research_store.workflow_type_for_task,
        )
        acceptance = AcceptResearch(
            research_store,
            temporal_client,
        )
        answers = AnswerResearch(ClarificationStore(engine), temporal_client)
    control_store = ControlStore(engine)
    control_controller = None
    if settings.control_enabled:
        assert settings.temporal is not None
        control_controller = ControlController(
            control_store,
            ConnectingTemporalControlStarter(
                settings.temporal.address,
                settings.temporal.namespace,
                settings.temporal.task_queue,
            ),
        )
    app = create_app(
        router(engine, verifier),
        research_router(
            IdentityAccess(engine, verifier),
            source,
            store=research_store,
            acceptance=acceptance,
            answers=answers,
            reports=ReportStore(engine),
        ),
        plan_router=discovery_router(
            IdentityAccess(engine, verifier), PlanStore(engine)
        ),
        control_router=make_control_router(
            IdentityAccess(engine, verifier), control_store, control_controller
        ),
        catalog_router=make_catalog_router(engine),
        library_router=make_library_router(
            IdentityAccess(engine, verifier), LibraryStore(engine)
        ),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            if settings.recovery_required:
                assert_recovery_ready(engine)
            yield
        finally:
            engine.dispose()

    app.router.lifespan_context = lifespan

    @app.get("/health/ready")
    def readiness() -> dict[str, str]:
        assert_recovery_ready(engine)
        return {"status": "ok"}

    return app


def create_app(
    identity_router: APIRouter | None = None,
    observation_router: APIRouter | None = None,
    plan_router: APIRouter | None = None,
    control_router: APIRouter | None = None,
    catalog_router: APIRouter | None = None,
    library_router: APIRouter | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Whisky Discovery Agent",
        responses={
            status: {"model": ErrorView}
            for status in (401, 403, 404, 409, 422, 429, 503)
        },
    )
    app.include_router(
        identity_router if identity_router is not None else router(None, None)
    )
    app.include_router(
        catalog_router if catalog_router is not None else make_catalog_router(None)
    )
    app.include_router(
        observation_router
        if observation_router is not None
        else research_router(IdentityAccess(None, None), None)
    )
    app.include_router(
        plan_router
        if plan_router is not None
        else discovery_router(IdentityAccess(None, None), None)
    )
    app.include_router(
        control_router
        if control_router is not None
        else make_control_router(IdentityAccess(None, None), None, None)
    )
    app.include_router(
        library_router
        if library_router is not None
        else make_library_router(IdentityAccess(None, None), None)
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
        if request.url.path == "/agent" or request.url.path.startswith(
            ("/api/", "/agent/")
        ):
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
        code = codes.get(error.status_code, "REQUEST_REJECTED")
        return error_response(
            error.status_code,
            code,
            request.state.request_id,
            error.headers,
        )

    @app.exception_handler(PublicAPIError)
    async def public_error(request: Request, error: PublicAPIError) -> Response:
        return error_response(error.status, error.code, request.state.request_id)

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
