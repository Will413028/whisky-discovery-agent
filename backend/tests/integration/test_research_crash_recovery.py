"""A killed worker must not strand or duplicate a saved clarification."""

import asyncio
import multiprocessing
from uuid import UUID, uuid4

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from research_worker_process import run_worker
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from test_catalog_release import synthetic_versioned_release
from test_research_clarification_workflow import task_reaches

from whisky.modules.catalog.store import CatalogStore
from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.contracts import AnswerResult
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.temporal_start import TemporalResearchStarter

pytestmark = pytest.mark.integration


async def _start_worker(context, address, namespace, queue, database_url):
    parent, child = context.Pipe()
    process = context.Process(
        target=run_worker,
        args=(address, namespace, queue, database_url, child),
    )
    process.start()
    child.close()
    assert await asyncio.to_thread(parent.poll, 20), "worker did not start"
    assert parent.recv() == "ready"
    return process, parent


async def _stop_worker(process, control):
    if process.is_alive():
        control.send("stop")
        await asyncio.to_thread(process.join, 15)
    if process.is_alive():
        process.kill()
        await asyncio.to_thread(process.join, 5)
    control.close()


async def test_killed_worker_resumes_saved_question_once(research_context):
    engine, research, (actor, _), plan = research_context
    CatalogStore(engine).publish(synthetic_versioned_release())
    process_context = multiprocessing.get_context("spawn")
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t09-kill-{uuid4()}"
        address = env.client.service_client.config.target_host
        first, first_control = await _start_worker(
            process_context, address, env.client.namespace, queue, str(engine.url)
        )
        try:
            receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "kill")
            run_id = await TemporalResearchStarter(
                client, queue, workflow_type="ResearchWorkflowV2"
            ).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            waiting = await task_reaches(
                research, receipt.task_id, actor.id, {"needs_input", "failed"}
            )
            assert waiting.status == "needs_input" and waiting.question is not None
            question = waiting.question
            first.kill()
            await asyncio.to_thread(first.join, 10)
            assert first.exitcode is not None and first.exitcode != 0
        finally:
            if first.is_alive():
                first.kill()
                await asyncio.to_thread(first.join, 5)
            first_control.close()

        answer = ClarificationStore(engine).reserve_answer(
            actor.id,
            actor.generation,
            receipt.task_id,
            question.id,
            question.waiting_version,
            1,
            "kill-answer",
            str(question.choices[1].id),
        )
        second, second_control = await _start_worker(
            process_context, address, env.client.namespace, queue, str(engine.url)
        )
        try:
            handle = client.get_workflow_handle(receipt.workflow_id)
            accepted = await handle.execute_update(
                "answer", answer, id=str(answer.id), result_type=AnswerResult
            )
            assert accepted.acceptance == "accepted"
            report_id = UUID(await asyncio.wait_for(handle.result(), 25))
            assert research.task(receipt.task_id, actor.id).status == "completed"
            report = ReportStore(engine).read(actor.id, report_id)
            assert report is not None
            assert report.clarified_bottle is not None
            assert report.clarified_bottle.question_id == question.id
            assert ReportStore(engine).read(actor.id, report_id) == report
        finally:
            await _stop_worker(second, second_control)
