import asyncio
import json
import socket
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import uvicorn
from httpx import AsyncClient
from temporalio.testing import WorkflowEnvironment

from whisky.bootstrap.api import configured_app
from whisky.bootstrap.settings import Settings
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


async def first_snapshot(response):
    assert response.status_code == 200
    async for line in response.aiter_lines():
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
                snapshot = await first_snapshot(response)
                command_id = response.headers["x-command-id"]
                assert snapshot["status"] == "queued"
            first = await env.client.get_workflow_handle(
                f"whisky-research-{snapshot['taskId']}"
            ).describe()
            # Close the HTTP connection before the 60s observation ends.
            async with client.stream(
                "POST", "/agent", json=payload, headers=headers
            ) as response:
                replay = await first_snapshot(response)
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
