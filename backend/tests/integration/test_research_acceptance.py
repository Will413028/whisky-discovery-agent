import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from test_research_start import CompletedResearchFixture, LoseFirstResponse

from whisky.modules.research.acceptance import AcceptResearch
from whisky.modules.research.report import ReportDraft
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.temporal_start import TemporalResearchStarter

pytestmark = pytest.mark.integration


def save_fixture_report(engine, actor, task_id):
    return ReportStore(engine).save(
        actor.id,
        actor.generation,
        task_id,
        "fixture-final-v1",
        ReportDraft(summary="受理對帳測試報告", candidates=()),
        policy_version="price-30d-v1",
        prompt_version="research-v1",
        model_version="fixture-v1",
    )


async def test_committed_pending_receipt_recovers_after_interruption(research_context):
    _, store, (actor, _), plan = research_context
    original = store.reserve(actor.id, actor.generation, plan.id, 1, "interrupted")
    async with await WorkflowEnvironment.start_local() as env:
        service = AcceptResearch(
            store, TemporalResearchStarter(env.client, f"test-{uuid4()}")
        )
        recovered = await service.execute(
            actor.id, actor.generation, plan.id, 1, "interrupted"
        )
        assert recovered.acceptance == "accepted"
        assert recovered.task_id == original.task_id
        assert (
            await env.client.get_workflow_handle(original.workflow_id).describe()
        ).run_id
        assert store.task(original.task_id, actor.id).status == "queued"


async def test_lost_response_keeps_pending_then_finds_original(research_context):
    _, store, (actor, _), plan = research_context
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(
            **{**env.client.config(), "interceptors": [LoseFirstResponse()]}
        )
        service = AcceptResearch(
            store, TemporalResearchStarter(client, f"test-{uuid4()}")
        )
        pending = await service.execute(actor.id, actor.generation, plan.id, 1, "lost")
        assert pending.acceptance == "acceptance_pending"
        assert store.task(pending.task_id, actor.id).status == "acceptance_pending"
        original = await env.client.get_workflow_handle(pending.workflow_id).describe()
        recovered = await service.execute(
            actor.id, actor.generation, plan.id, 1, "lost"
        )
        assert recovered.acceptance == "accepted"
        assert recovered.task_id == pending.task_id
        assert (
            await env.client.get_workflow_handle(pending.workflow_id).describe()
        ).run_id == original.run_id


async def test_parallel_commands_use_one_task_and_temporal_run(research_context):
    engine, store, (actor, _), plan = research_context
    async with await WorkflowEnvironment.start_local() as env:
        service = AcceptResearch(
            store, TemporalResearchStarter(env.client, f"test-{uuid4()}")
        )
        results = await asyncio.gather(
            *(
                service.execute(actor.id, actor.generation, plan.id, 1, "parallel")
                for _ in range(2)
            )
        )
        assert results[0] == results[1]
        assert results[0].acceptance == "accepted"
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM research_tasks")) == 1
            run_id = connection.scalar(
                text("SELECT temporal_run_id FROM research_tasks")
            )
        assert (
            await env.client.get_workflow_handle(results[0].workflow_id).describe()
        ).run_id == run_id


async def test_completed_receipt_retry_does_not_contact_temporal(research_context):
    engine, store, (actor, _), plan = research_context
    async with await WorkflowEnvironment.start_local() as env:
        queue = f"test-{uuid4()}"
        async with Worker(
            env.client, task_queue=queue, workflows=[CompletedResearchFixture]
        ):
            service = AcceptResearch(store, TemporalResearchStarter(env.client, queue))
            receipt = await service.execute(
                actor.id, actor.generation, plan.id, 1, "completed"
            )
            assert receipt.acceptance == "accepted"
            assert await env.client.get_workflow_handle(
                receipt.workflow_id
            ).result() == str(receipt.task_id)
            save_fixture_report(engine, actor, receipt.task_id)

        class UnavailableStarter:
            async def start(self, task_id):
                pytest.fail(
                    "accepted receipt must not depend on retained Temporal history"
                )

        retry = AcceptResearch(store, UnavailableStarter())
        assert (
            await retry.execute(actor.id, actor.generation, plan.id, 1, "completed")
            == receipt
        )
        assert store.task(receipt.task_id, actor.id).status == "completed"


@pytest.mark.parametrize("write_allowed", [True, False])
async def test_completed_task_reconciles_pending_receipt_without_temporal(
    research_context,
    write_allowed,
):
    engine, store, (actor, _), plan = research_context
    async with await WorkflowEnvironment.start_local() as env:
        queue = f"test-{uuid4()}"
        client = Client(
            **{**env.client.config(), "interceptors": [LoseFirstResponse()]}
        )
        async with Worker(
            env.client, task_queue=queue, workflows=[CompletedResearchFixture]
        ):
            service = AcceptResearch(store, TemporalResearchStarter(client, queue))
            pending = await service.execute(
                actor.id, actor.generation, plan.id, 1, "lost-completed"
            )
            assert pending.acceptance == "acceptance_pending"
            assert await env.client.get_workflow_handle(
                pending.workflow_id
            ).result() == str(pending.task_id)
            save_fixture_report(engine, actor, pending.task_id)
            if not write_allowed:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE research_tasks SET write_allowed=false WHERE id=:id"
                        ),
                        {"id": pending.task_id},
                    )

        class ForbiddenStarter:
            async def start(self, task_id):
                pytest.fail(
                    "completed product task must not restart "
                    "even with a pending receipt"
                )

        recovered = await AcceptResearch(store, ForbiddenStarter()).execute(
            actor.id, actor.generation, plan.id, 1, "lost-completed"
        )
        assert recovered.acceptance == "accepted"
        assert recovered.task_id == pending.task_id
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT status FROM research_commands"))
                == "accepted"
            )
        assert store.task(pending.task_id, actor.id).status == "completed"


async def test_start_deadline_preserves_committed_pending_receipt(research_context):
    _, store, (actor, _), plan = research_context
    cancelled = asyncio.Event()

    class SlowStarter:
        async def start(self, task_id):
            try:
                await asyncio.sleep(30)
                return "late"
            finally:
                cancelled.set()

    service = AcceptResearch(store, SlowStarter(), start_timeout=0.02)
    async with asyncio.timeout(3):
        receipt = await service.execute(
            actor.id, actor.generation, plan.id, 1, "deadline"
        )
    assert receipt.acceptance == "acceptance_pending"
    assert store.task(receipt.task_id, actor.id).status == "acceptance_pending"
    assert cancelled.is_set()
