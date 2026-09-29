"""A hard price failure is determined from reviewed rules without model prose."""

import asyncio
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.models.function import FunctionModel
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from test_catalog_release import synthetic_release

from whisky.bootstrap.worker import research_worker
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import Preference, ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.temporal_start import TemporalResearchStarter

pytestmark = pytest.mark.integration


async def test_no_qualified_price_produces_grounded_empty_report(research_context):
    engine, research, (actor, _), _ = research_context
    CatalogStore(engine).publish(synthetic_release())
    plan = PlanStore(engine).create(
        actor.id,
        actor.generation,
        "budget",
        ResearchConditions(
            entry="beginner",
            goal="找 800 元內的 Synthetic test bottle",
            budget_twd=Decimal("800"),
        ),
    )

    def model(messages, info):
        raise AssertionError("The hard budget conclusion must not rely on a model")

    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t08-empty-budget-{uuid4()}"
        async with research_worker(client, queue, engine, FunctionModel(model)):
            receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "budget")
            run_id = await TemporalResearchStarter(
                client, queue, workflow_type="ResearchWorkflowV3"
            ).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            report_id = await asyncio.wait_for(
                client.get_workflow_handle(receipt.workflow_id).result(), timeout=20
            )
    report = ReportStore(engine).read(actor.id, UUID(report_id))
    assert report is not None
    assert not report.candidates
    assert "800" in report.summary
    assert "Synthetic test bottle" in report.unresolved[0]


async def test_unprovable_hard_avoidance_stops_before_model(research_context):
    engine, research, (actor, _), _ = research_context
    CatalogStore(engine).publish(synthetic_release())
    plan = PlanStore(engine).create(
        actor.id,
        actor.generation,
        "avoid unknown",
        ResearchConditions(
            entry="beginner",
            goal="找下一款",
            preferences=(
                Preference(
                    description="煙燻",
                    intent="avoid",
                    certainty="user_stated",
                    strength="hard",
                ),
            ),
        ),
    )

    def model(messages, info):
        raise AssertionError("An unprovable hard preference must not reach a model")

    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t08-hard-avoid-{uuid4()}"
        async with research_worker(client, queue, engine, FunctionModel(model)):
            receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "avoid")
            run_id = await TemporalResearchStarter(
                client, queue, workflow_type="ResearchWorkflowV3"
            ).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            report_id = await asyncio.wait_for(
                client.get_workflow_handle(receipt.workflow_id).result(), timeout=20
            )
    report = ReportStore(engine).read(actor.id, UUID(report_id))
    assert report is not None
    assert not report.candidates
    assert "硬偏好「煙燻」" in report.unresolved[0]
