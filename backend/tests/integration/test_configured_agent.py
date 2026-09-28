import asyncio
import json
import socket
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import uvicorn
from httpx import AsyncClient
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import text
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from test_catalog_release import synthetic_release
from test_research_workflow import controlled_model

from whisky.bootstrap.api import configured_app
from whisky.bootstrap.settings import Settings
from whisky.bootstrap.worker import research_worker
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.public import IdentityAccess

pytestmark = pytest.mark.integration


@asynccontextmanager
async def serve(app):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="critical", timeout_graceful_shutdown=2)
    )
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        listener.close()


async def first_snapshot(lines):
    async for line in lines:
        if line.startswith("data: "):
            event = json.loads(line[6:])
            if event["type"] == "STATE_SNAPSHOT":
                return event["snapshot"]
    raise AssertionError("Stream ended before its snapshot")


async def test_configured_app_starts_real_temporal_and_recovers_after_socket_close(
    research_context, signed_tokens, monkeypatch
):
    engine, _, _, _ = research_context
    verifier, sign = signed_tokens
    monkeypatch.setattr("whisky.bootstrap.api.TokenVerifier", lambda *_: verifier)
    actor = IdentityAccess(engine, verifier).authenticate(sign())
    plan = PlanStore(engine).create(
        actor.actor_id,
        actor.generation,
        "configured",
        ResearchConditions(entry="beginner", goal="configured research"),
    )
    async with await WorkflowEnvironment.start_local() as env:
        settings = Settings.from_environment(
            {
                "WHISKY_DATABASE_URL": str(engine.url),
                "WHISKY_AUTH0_ISSUER": "https://whisky-fixture.example/",
                "WHISKY_AUTH0_AUDIENCE": "https://whisky-api.example",
                "WHISKY_TEMPORAL_ADDRESS": env.client.service_client.config.target_host,
                "WHISKY_TEMPORAL_NAMESPACE": env.client.namespace,
                "WHISKY_TEMPORAL_TASK_QUEUE": f"test-{uuid4()}",
            }
        )
        app = configured_app(settings)
        payload = dict(
            threadId=str(uuid4()),
            runId=str(uuid4()),
            messages=[],
            tools=[],
            context=[],
            state={},
            forwardedProps=dict(
                type="start", key="first", planId=str(plan.id), conditionsRevision=1
            ),
        )
        async with (
            serve(app) as origin,
            AsyncClient(base_url=origin, timeout=5) as client,
        ):
            headers = {"Authorization": f"Bearer {sign()}"}
            async with client.stream(
                "POST", "/agent", json=payload, headers=headers
            ) as response:
                assert response.status_code == 200
                snapshot = await first_snapshot(response.aiter_lines())
                command_id = response.headers["x-command-id"]
                assert snapshot["status"] == "queued"
            first = await env.client.get_workflow_handle(
                f"whisky-research-{snapshot['taskId']}"
            ).describe()
            # Close the HTTP connection before the 60s observation ends.
            async with client.stream(
                "POST", "/agent", json=payload, headers=headers
            ) as response:
                assert response.status_code == 200
                replay = await first_snapshot(response.aiter_lines())
                assert replay["taskId"] == snapshot["taskId"]
                assert response.headers["x-command-id"] == command_id
            second = await env.client.get_workflow_handle(
                f"whisky-research-{snapshot['taskId']}"
            ).describe()
            assert first.run_id == second.run_id
            restored = await client.get(
                f"/api/v1/tasks/{snapshot['taskId']}", headers=headers
            )
            assert restored.json()["status"] == "queued"


@pytest.mark.parametrize(
    ("disconnect", "invalid"), [(True, False), (False, False), (False, True)]
)
async def test_http_observer_gets_terminal_report_or_recovers_after_disconnect(
    research_context, signed_tokens, monkeypatch, disconnect, invalid
):
    engine, _, _, _ = research_context
    CatalogStore(engine).publish(synthetic_release())
    verifier, sign = signed_tokens
    monkeypatch.setattr("whisky.bootstrap.api.TokenVerifier", lambda *_: verifier)
    actor = IdentityAccess(engine, verifier).authenticate(sign())
    plan = PlanStore(engine).create(
        actor.actor_id,
        actor.generation,
        "disconnect",
        ResearchConditions(entry="beginner", goal="find reviewed whisky"),
    )
    model_started = asyncio.Event()
    allow_model = asyncio.Event()

    async def held_model(messages, info):
        model_started.set()
        await allow_model.wait()
        response = controlled_model(messages, info)
        if invalid and any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        ):
            response.parts[0].args["candidates"][0]["claims"][0]["value"] = (
                "沒有來源的事實"
            )
        return response

    async with await WorkflowEnvironment.start_local() as env:
        queue = f"test-{uuid4()}"
        worker_client = Client(
            **{**env.client.config(), "plugins": [PydanticAIPlugin()]}
        )
        settings = Settings.from_environment(
            {
                "WHISKY_DATABASE_URL": str(engine.url),
                "WHISKY_AUTH0_ISSUER": "https://whisky-fixture.example/",
                "WHISKY_AUTH0_AUDIENCE": "https://whisky-api.example",
                "WHISKY_TEMPORAL_ADDRESS": env.client.service_client.config.target_host,
                "WHISKY_TEMPORAL_NAMESPACE": env.client.namespace,
                "WHISKY_TEMPORAL_TASK_QUEUE": queue,
            }
        )
        app = configured_app(settings)
        payload = dict(
            threadId=str(uuid4()),
            runId=str(uuid4()),
            messages=[],
            tools=[],
            context=[],
            state={},
            forwardedProps=dict(
                type="start",
                key="disconnect",
                planId=str(plan.id),
                conditionsRevision=1,
            ),
        )
        async with (
            research_worker(worker_client, queue, engine, FunctionModel(held_model)),
            serve(app) as origin,
            AsyncClient(base_url=origin, timeout=10) as client,
        ):
            headers = {"Authorization": f"Bearer {sign()}"}
            async with client.stream(
                "POST", "/agent", json=payload, headers=headers
            ) as response:
                assert response.status_code == 200
                lines = response.aiter_lines()
                snapshot = await first_snapshot(lines)
                assert snapshot["taskId"]
                await asyncio.wait_for(model_started.wait(), timeout=10)
                if not disconnect:
                    allow_model.set()
                    terminal = []
                    async for line in lines:
                        if line.startswith("data: "):
                            event = json.loads(line[6:])
                            terminal.append(event)
                            if event["type"] in {"RUN_FINISHED", "RUN_ERROR"}:
                                break
                    if invalid:
                        assert terminal[-1]["type"] == "RUN_ERROR"
                        assert terminal[-1]["code"] == "RESEARCH_FAILED"
                    else:
                        assert terminal[-1]["type"] == "RUN_FINISHED"
                        assert terminal[-1]["outcome"]["type"] == "success"
                        assert any(
                            event["type"] == "CUSTOM"
                            and event["name"] == "whisky.report"
                            for event in terminal
                        )
            if disconnect:
                allow_model.set()
            workflow_id = f"whisky-research-{snapshot['taskId']}"
            if invalid:
                with pytest.raises(Exception):
                    await asyncio.wait_for(
                        worker_client.get_workflow_handle(workflow_id).result(),
                        timeout=20,
                    )
            else:
                report_id = await asyncio.wait_for(
                    worker_client.get_workflow_handle(workflow_id).result(),
                    timeout=20,
                )
            restored = await client.get(
                f"/api/v1/tasks/{snapshot['taskId']}", headers=headers
            )
            assert restored.status_code == 200
            assert restored.json()["status"] == ("failed" if invalid else "completed")
            if not invalid:
                assert restored.json()["reportId"] == report_id
                report = await client.get(
                    f"/api/v1/reports/{report_id}", headers=headers
                )
                assert report.status_code == 200
            with engine.connect() as connection:
                outcome = connection.scalar(
                    text("SELECT outcome FROM agent_turns WHERE task_id=:task"),
                    {"task": snapshot["taskId"]},
                )
                assert outcome == (
                    {"type": "error", "code": "RESEARCH_FAILED"}
                    if invalid
                    else {"type": "success", "reportId": report_id}
                )
