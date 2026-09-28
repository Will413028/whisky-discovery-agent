import json
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from test_research_start import LoseFirstResponse

from whisky.bootstrap.api import create_app
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.public import IdentityAccess
from whisky.modules.research.acceptance import AcceptResearch
from whisky.modules.research.http import observation_router
from whisky.modules.research.observation import ObservationPolicy
from whisky.modules.research.temporal_start import TemporalResearchStarter

pytestmark = pytest.mark.integration


def events(response):
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.fixture
async def agent_context(research_context, signed_tokens):
    engine, store, _, _ = research_context
    verifier, sign = signed_tokens
    identity = IdentityAccess(engine, verifier)
    actor = identity.authenticate(sign())
    plan = PlanStore(engine).create(
        actor.actor_id,
        actor.generation,
        "agent-plan",
        ResearchConditions(entry="beginner", goal="果香"),
    )
    payload = dict(
        threadId=str(uuid4()),
        runId=str(uuid4()),
        messages=[],
        state={},
        tools=[],
        context=[],
        forwardedProps=dict(
            type="start", key="agent-start", planId=str(plan.id), conditionsRevision=1
        ),
    )
    yield engine, store, identity, actor, sign, payload


@pytest.mark.parametrize("lose_response", [False, True])
async def test_agent_start_and_observe_share_persisted_turn(
    agent_context, lose_response
):
    engine, store, identity, actor, sign, payload = agent_context
    async with await WorkflowEnvironment.start_local() as env:
        temporal = (
            Client(**{**env.client.config(), "interceptors": [LoseFirstResponse()]})
            if lose_response
            else env.client
        )
        acceptance = AcceptResearch(
            store, TemporalResearchStarter(temporal, f"test-{uuid4()}")
        )
        app = create_app(
            observation_router=observation_router(
                identity,
                None,
                ObservationPolicy(lifetime_seconds=2, poll_seconds=10),
                store=store,
                acceptance=acceptance,
            )
        )
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            headers = {"Authorization": f"Bearer {sign()}"}
            first = await client.post("/agent", json=payload, headers=headers)
            assert first.status_code == 200, first.text
            assert first.headers["cache-control"] == "no-store"
            stream = events(first)
            assert stream[0]["type"] == "RUN_STARTED"
            assert (
                stream[0]["threadId"] == payload["threadId"]
                and stream[0]["runId"] == payload["runId"]
            )
            snapshot = stream[1]["snapshot"]
            assert snapshot["status"] == (
                "acceptance_pending" if lose_response else "queued"
            )
            assert all(event["type"] != "RUN_FINISHED" for event in stream)
            command_id = first.headers["x-command-id"]
            recovered = await client.post("/agent", json=payload, headers=headers)
            assert recovered.status_code == 200, recovered.text
            assert recovered.headers["x-command-id"] == command_id
            assert events(recovered)[1]["snapshot"]["taskId"] == snapshot["taskId"]
            assert events(recovered)[1]["snapshot"]["status"] == "queued"
            observe = dict(
                taskId=snapshot["taskId"], runId=payload["runId"], conditionsRevision=1
            )
            restored = await client.post(
                "/agent/observe", json=observe, headers=headers
            )
            assert restored.status_code == 200
            assert events(restored)[1]["snapshot"]["taskId"] == snapshot["taskId"]
            for changes in [dict(runId=str(uuid4())), dict(conditionsRevision=2)]:
                rejected = await client.post(
                    "/agent/observe", json={**observe, **changes}, headers=headers
                )
                assert rejected.status_code == 404
            foreign = await client.post(
                "/agent/observe",
                json=observe,
                headers={"Authorization": f"Bearer {sign(sub='foreign')}"},
            )
            assert foreign.status_code == 404
            conflict = await client.post(
                "/agent", json={**payload, "runId": str(uuid4())}, headers=headers
            )
            assert conflict.status_code == 409
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT workflow_id FROM research_tasks WHERE owner_id = :owner"
                    ),
                    dict(owner=actor.actor_id),
                ).all()
                assert len(rows) == 1
                assert (
                    await env.client.get_workflow_handle(rows[0].workflow_id).describe()
                ).run_id


async def test_agent_validates_auth_and_command_before_start(agent_context):
    _, store, identity, _, sign, payload = agent_context
    app = create_app(observation_router=observation_router(identity, None, store=store))
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.post("/agent", json=payload)).status_code == 401
        headers = {"Authorization": f"Bearer {sign()}"}
        response = await client.post("/agent", json=payload, headers=headers)
        assert (
            response.status_code == 503
            and response.json()["code"] == "RESEARCH_UNAVAILABLE"
        )
        invalid = {
            **payload,
            "forwardedProps": {**payload["forwardedProps"], "owner": "foreign"},
        }
        assert (
            await client.post("/agent", json=invalid, headers=headers)
        ).status_code == 422
