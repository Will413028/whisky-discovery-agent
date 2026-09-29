"""V3 questions display reviewed version labels, not model-invented facts."""

import asyncio
from uuid import uuid4

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.models.function import FunctionModel
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from test_catalog_release import synthetic_versioned_release

from whisky.bootstrap.worker import research_worker
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.research.temporal_start import TemporalResearchStarter

pytestmark = pytest.mark.integration


async def test_v3_question_uses_reviewed_names_instead_of_model_claims(
    research_context,
):
    engine, research, (actor, _), _ = research_context
    release = synthetic_versioned_release()
    CatalogStore(engine).publish(release)
    plan = PlanStore(engine).create(
        actor.id,
        actor.generation,
        "version",
        ResearchConditions(
            entry="beginner",
            goal="不確定喝過 Synthetic test bottle 12 年或 15 年，想先確認版本",
        ),
    )

    def model(messages, info):
        raise AssertionError("Explicit version ambiguity is a reviewed-data rule")

    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t08-reviewed-question-{uuid4()}"
        async with research_worker(client, queue, engine, FunctionModel(model)):
            receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "safe")
            run_id = await TemporalResearchStarter(
                client, queue, workflow_type="ResearchWorkflowV3"
            ).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            handle = client.get_workflow_handle(receipt.workflow_id)
            async with asyncio.timeout(20):
                while True:
                    view = research.task(receipt.task_id, actor.id)
                    if view is not None and view.status == "needs_input":
                        break
                    await asyncio.sleep(0.05)
            assert view.question is not None
            assert "葡萄" not in view.question.prompt
            assert all(item.name in view.question.prompt for item in release.items)
            await handle.cancel()
