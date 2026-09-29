"""Provider errors follow a bounded retry policy and debit each attempt."""

import asyncio
from uuid import uuid4

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import text
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from test_catalog_release import synthetic_release

from whisky.bootstrap.worker import WORKERS_AI_MODEL, research_worker
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.research.quota import QuotaStore
from whisky.modules.research.temporal_start import TemporalResearchStarter

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("status_code", "body", "expected_calls"),
    [
        (400, {"code": 3030}, 1),
        (429, {"error": {"code": 3036}}, 1),
        (429, {"errors": [{"code": 3040}]}, 3),
        (429, {"error": {"code": 9999}}, 1),
        (500, {"code": 5000, "message": "provider should not leak input"}, 3),
    ],
)
async def test_provider_retry_policy_is_bounded(
    research_context, status_code, body, expected_calls
):
    engine, research, (actor, _), plan = research_context
    CatalogStore(engine).publish(synthetic_release())
    calls = 0
    message_bytes = []

    def model(_messages, info):
        nonlocal calls
        calls += 1
        message_bytes.append(len(str(_messages).encode("utf-8")))
        assert info.model_settings is not None
        assert info.model_settings["max_tokens"] == 2000
        assert info.model_settings["parallel_tool_calls"] is False
        raise ModelHTTPError(
            status_code, WORKERS_AI_MODEL, body, headers={"Retry-After": "0"}
        )

    quota = QuotaStore(engine, daily_neuron_limit=1000)
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t08-model-policy-{uuid4()}"
        async with research_worker(
            client, queue, engine, FunctionModel(model), quota=quota
        ):
            receipt = research.reserve(
                actor.id, actor.generation, plan.id, 1, f"http-{status_code}"
            )
            run_id = await TemporalResearchStarter(
                client, queue, workflow_type="ResearchWorkflowV3"
            ).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            with pytest.raises(Exception):
                await asyncio.wait_for(
                    client.get_workflow_handle(receipt.workflow_id).result(), 20
                )
    assert calls == expected_calls
    with engine.connect() as connection:
        attempts = (
            connection.execute(
                text("""
            SELECT status,reserved_input_tokens FROM research_usage_attempts
            WHERE task_id=:task ORDER BY attempt
            """),
                dict(task=receipt.task_id),
            )
            .mappings()
            .all()
        )
    assert [attempt["status"] for attempt in attempts] == ["unknown"] * expected_calls
    assert all(
        attempt["reserved_input_tokens"] > max(message_bytes) for attempt in attempts
    )
    assert quota.daily_reserved_neurons() > 0
