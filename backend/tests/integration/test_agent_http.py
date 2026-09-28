import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from ag_ui.core import RunAgentInput
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from test_catalog_release import synthetic_versioned_release
from test_research_start import LoseFirstResponse

from whisky.bootstrap.api import create_app
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.public import IdentityAccess
from whisky.modules.research.acceptance import AcceptResearch
from whisky.modules.research.answer import AnswerResearch
from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.commands import parse_start
from whisky.modules.research.decision import ClarificationDraft
from whisky.modules.research.http import observation_router
from whisky.modules.research.observation import ObservationPolicy
from whisky.modules.research.run_store import ResearchRunStore
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


async def test_agent_resume_binds_new_run_to_original_task(agent_context):
    engine, store, identity, actor, sign, payload = agent_context
    start = parse_start(RunAgentInput.model_validate(payload))
    receipt = store.reserve_turn(actor.actor_id, actor.generation, start)
    store.confirm(actor.actor_id, actor.generation, receipt.id, str(uuid4()))
    context = ResearchRunStore(engine).begin(receipt.task_id)
    clarifications = ClarificationStore(engine)
    release = synthetic_versioned_release()
    CatalogStore(engine).publish(release)
    choices = tuple(str(item.bottle.version_id) for item in release.items)
    question = clarifications.publish(
        context,
        1,
        ClarificationDraft("哪個版本？", choices),
        datetime.now(UTC) + timedelta(days=7),
    )

    class Answerer:
        async def answer(self, command):
            return clarifications.accept_answer(command)

    app = create_app(
        observation_router=observation_router(
            identity,
            None,
            ObservationPolicy(lifetime_seconds=0.05, poll_seconds=10),
            store=store,
            answers=AnswerResearch(clarifications, Answerer()),
        )
    )
    resumed = {
        **payload,
        "runId": str(uuid4()),
        "forwardedProps": {
            "type": "answer",
            "key": "resume-version",
            "taskId": str(receipt.task_id),
            "conditionsRevision": 1,
            "waitingVersion": 1,
        },
        "resume": [
            {
                "interruptId": str(question.id),
                "status": "resolved",
                "payload": {"answer": choices[1]},
            }
        ],
    }
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/agent",
            json=resumed,
            headers={"Authorization": f"Bearer {sign()}"},
        )
    assert response.status_code == 200
    assert response.headers["x-command-id"]
    stream = events(response)
    assert stream[0]["runId"] == resumed["runId"]
    assert stream[1]["snapshot"]["taskId"] == str(receipt.task_id)
    assert stream[1]["snapshot"]["status"] == "researching"
    assert (
        store.observed_task(receipt.task_id, UUID(resumed["runId"]), actor.actor_id)
        is not None
    )
