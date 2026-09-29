"""A named reviewed bottle with no qualified price remains visibly excluded."""

import asyncio
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from whisky.bootstrap.worker import research_worker
from whisky.modules.catalog.publication import load_reviewed_release
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.source_reader import SourceReader
from whisky.modules.research.temporal_start import TemporalResearchStarter

pytestmark = pytest.mark.integration


async def test_named_solera_price_gap_is_preserved_with_other_eligible_candidates(
    research_context,
):
    engine, research, (actor, _), _ = research_context
    manifest = (
        Path(__file__).resolve().parents[3] / "data/catalog/first-journey.reviewed.json"
    ).read_text()
    CatalogStore(engine).publish(load_reviewed_release(manifest))
    plan = PlanStore(engine).create(
        actor.id,
        actor.generation,
        "Solera budget",
        ResearchConditions(
            entry="beginner",
            goal="格蘭菲迪 15 年 Solera 在 1500 元內嗎？給我可用候選",
            budget_twd=Decimal("1500"),
        ),
    )

    def model(messages, info):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"source_index": 1, "focus": "price"},
                )
            ]
        )

    async def fetch(_url: str, _limit: int):
        return 200, {"Content-Type": "text/html"}, b"<p>Reviewed fixture</p>"

    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t08-named-price-{uuid4()}"
        async with research_worker(
            client,
            queue,
            engine,
            FunctionModel(model),
            source_reader=SourceReader(fetch=fetch),
        ):
            receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "price")
            run_id = await TemporalResearchStarter(
                client, queue, workflow_type="ResearchWorkflowV3"
            ).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            report_id = await asyncio.wait_for(
                client.get_workflow_handle(receipt.workflow_id).result(), timeout=20
            )
    report = ReportStore(engine).read(actor.id, UUID(report_id))
    assert report is not None
    assert report.candidates
    assert all("Solera" not in item.name for item in report.candidates)
    assert any("格蘭菲迪 15 年 Solera" in note for note in report.unresolved)
