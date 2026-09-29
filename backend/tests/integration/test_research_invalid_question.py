"""Invalid model-selected source indexes fail before network I/O."""

import asyncio
from uuid import uuid4

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from test_catalog_release import synthetic_release

from whisky.bootstrap.worker import research_worker
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.research.source_reader import SourceReader
from whisky.modules.research.temporal_start import TemporalResearchStarter

pytestmark = pytest.mark.integration


async def test_invalid_source_choice_is_not_retried_or_fetched(research_context):
    engine, research, (actor, _), plan = research_context
    CatalogStore(engine).publish(synthetic_release())
    model_calls = 0
    fetches = 0

    def model(messages, info):
        nonlocal model_calls
        model_calls += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"source_index": 999, "focus": "flavor"},
                )
            ]
        )

    async def fetch(_url: str, _limit: int):
        nonlocal fetches
        fetches += 1
        return 200, {"Content-Type": "text/html"}, b"unreachable"

    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t08-invalid-{uuid4()}"
        async with research_worker(
            client,
            queue,
            engine,
            FunctionModel(model),
            source_reader=SourceReader(fetch=fetch),
        ):
            receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "bad")
            run_id = await TemporalResearchStarter(
                client, queue, workflow_type="ResearchWorkflowV3"
            ).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            with pytest.raises(Exception):
                await asyncio.wait_for(
                    client.get_workflow_handle(receipt.workflow_id).result(), 20
                )
    assert fetches == 0
    assert model_calls == 1
    assert research.task(receipt.task_id, actor.id).status == "failed"
