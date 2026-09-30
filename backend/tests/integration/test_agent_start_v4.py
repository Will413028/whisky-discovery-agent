"""New AG-UI starts preserve their V4 input and durable acceptance receipt."""

import asyncio
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import text
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from test_agent_http import agent_context as agent_context
from test_agent_http import events
from test_research_proposal_workflow_v4 import proposal_model

from whisky.bootstrap.api import create_app
from whisky.bootstrap.worker import research_worker
from whisky.modules.discovery.store import PlanStore
from whisky.modules.research.acceptance import AcceptResearch
from whisky.modules.research.http import observation_router
from whisky.modules.research.observation import ObservationPolicy
from whisky.modules.research.temporal_start import ConnectingTemporalResearchStarter

pytestmark = pytest.mark.integration


async def test_agent_start_v4_persists_input_and_replays_one_receipt(agent_context):
    engine, store, identity, actor, sign, original = agent_context
    payload = deepcopy(original)
    payload["forwardedProps"].update(
        type="start_v4",
        input={"schemaVersion": 4, "phase": "proposal", "sourceText": "我喜歡蜂蜜甜點"},
    )
    started = []

    class FixtureStarter:
        async def start(self, task_id):
            started.append(task_id)
            return "fixture-run-v4"

    app = create_app(
        observation_router=observation_router(
            identity,
            None,
            ObservationPolicy(lifetime_seconds=2, poll_seconds=10),
            store=store,
            acceptance=AcceptResearch(store, FixtureStarter()),
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        headers = {"Authorization": f"Bearer {sign()}"}
        first = await client.post("/agent", json=payload, headers=headers)
        assert first.status_code == 200, first.text
        task_id = UUID(events(first)[1]["snapshot"]["taskId"])
        retry = await client.post("/agent", json=payload, headers=headers)
        assert retry.status_code == 200
        assert retry.headers["x-command-id"] == first.headers["x-command-id"]
        assert started == [task_id]
        changed = deepcopy(payload)
        changed["forwardedProps"]["input"]["sourceText"] = "我不喜歡蜂蜜甜點"
        assert (
            await client.post("/agent", json=changed, headers=headers)
        ).status_code == 409
    with engine.connect() as connection:
        saved = connection.execute(
            text("SELECT owner_id,input FROM research_v4_inputs WHERE task_id=:id"),
            {"id": task_id},
        ).one()
        assert saved.owner_id == actor.actor_id
        assert saved.input["sourceText"] == "我喜歡蜂蜜甜點"


async def test_agent_start_v4_rejects_invalid_input_before_reservation(agent_context):
    engine, store, identity, _, sign, original = agent_context
    payload = deepcopy(original)
    payload["forwardedProps"].update(type="start_v4", input={"phase": "proposal"})
    app = create_app(observation_router=observation_router(identity, None, store=store))
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/agent", json=payload, headers={"Authorization": f"Bearer {sign()}"}
        )
        assert response.status_code == 422
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM research_tasks")) == 0


async def test_http_v4_reaches_real_durable_proposal_workflow(agent_context):
    engine, store, identity, actor, sign, original = agent_context
    payload = deepcopy(original)
    payload["forwardedProps"].update(
        type="start_v4",
        input={"phase": "proposal", "sourceText": "我喜歡甜點，還不知道喜歡哪種威士忌"},
    )
    before = PlanStore(engine).read(
        UUID(payload["forwardedProps"]["planId"]), actor.actor_id
    )
    async with await WorkflowEnvironment.start_local() as env:
        temporal = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"test-http-v4-{uuid4()}"
        starter = ConnectingTemporalResearchStarter(
            "unused-fixture-address",
            "default",
            queue,
            workflow_type_for_task=store.workflow_type_for_task,
        )
        starter._client = temporal
        app = create_app(
            observation_router=observation_router(
                identity,
                None,
                ObservationPolicy(lifetime_seconds=2, poll_seconds=10),
                store=store,
                acceptance=AcceptResearch(store, starter),
            )
        )
        async with research_worker(
            temporal, queue, engine, FunctionModel(proposal_model)
        ):
            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/agent",
                    json=payload,
                    headers={"Authorization": f"Bearer {sign()}"},
                )
                assert response.status_code == 200, response.text
                task_id = UUID(events(response)[1]["snapshot"]["taskId"])
                async with asyncio.timeout(15):
                    while True:
                        task = store.task(task_id, actor.actor_id)
                        if task.status in {"needs_input", "failed"}:
                            break
                        await asyncio.sleep(0.05)
                assert task.status == "needs_input"
                assert (
                    task.question is not None and "偏好仍未確認" in task.question.prompt
                )
                assert (
                    PlanStore(engine).read(before.id, actor.actor_id).conditions
                    == before.conditions
                )
                description = await temporal.get_workflow_handle(
                    f"whisky-research-{task_id}"
                ).describe()
                assert description.workflow_type == "ResearchWorkflowV4"
                await temporal.get_workflow_handle(
                    f"whisky-research-{task_id}"
                ).cancel()
