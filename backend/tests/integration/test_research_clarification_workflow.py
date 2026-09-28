"""The model-selected question must suspend the same durable workflow."""

import asyncio
import json
import multiprocessing
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from research_worker_process import run_worker
from temporalio import activity
from temporalio.client import Client, WorkflowUpdateStage
from temporalio.testing import WorkflowEnvironment
from test_catalog_release import synthetic_versioned_release

from whisky.bootstrap.worker import research_worker
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.research.activities import ResearchActivities
from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.contracts import (
    AnswerResult,
    PublishedQuestion,
    QuestionCommit,
)
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.temporal_start import TemporalResearchStarter

pytestmark = pytest.mark.integration


async def task_reaches(research, task_id, owner, expected: set[str]):
    async with asyncio.timeout(12):
        while True:
            view = research.task(task_id, owner)
            if view.status in expected:
                return view
            await asyncio.sleep(0.05)


def clarifying_model(messages, info):
    returns = [
        part
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    if not returns:
        return ModelResponse(parts=[ToolCallPart("search_reviewed_catalog", {})])
    options = returns[-1].content
    if isinstance(options, str):
        options = json.loads(options)
    return ModelResponse(
        parts=[
            ToolCallPart(
                info.output_tools[0].name,
                {
                    "report": None,
                    "clarification": {
                        "prompt": "你指的是哪個版本？",
                        "choices": [
                            option["bottle_version_id"] for option in options[:2]
                        ],
                    },
                },
            )
        ]
    )


async def test_model_question_becomes_durable_wait(research_context):
    engine, research, (actor, _), plan = research_context
    release = synthetic_versioned_release()
    CatalogStore(engine).publish(release)
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t06-{uuid4()}"
        async with research_worker(
            client, queue, engine, FunctionModel(clarifying_model)
        ):
            receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "ask")
            run_id = await TemporalResearchStarter(
                client, queue, workflow_type="ResearchWorkflowV2"
            ).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            view = await task_reaches(
                research, receipt.task_id, actor.id, {"needs_input", "failed"}
            )
            assert view.status == "needs_input"
            assert view.question is not None
            assert {choice.id for choice in view.question.choices} == {
                item.bottle.version_id for item in release.items
            }
            await client.get_workflow_handle(receipt.workflow_id).cancel()


async def test_answer_after_worker_restart_searches_the_new_catalog_release(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    first_release = synthetic_versioned_release()
    CatalogStore(engine).publish(first_release)
    lookup_calls = 0

    def model(messages, info):
        nonlocal lookup_calls
        returns = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if not returns:
            lookup_calls += 1
            return ModelResponse(parts=[ToolCallPart("search_reviewed_catalog", {})])
        options = returns[-1].content
        if isinstance(options, str):
            options = json.loads(options)
        if "Previously clarified: Question:" not in str(messages):
            return clarifying_model(messages, info)
        option = options[0]
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "report": {
                            "summary": "補充後重新查核正式資料",
                            "candidates": [
                                {
                                    "release_id": option["release_id"],
                                    "item_id": option["item_id"],
                                    "claims": [option["facts"][0]],
                                    "reason": "來源與版本已核對",
                                    "price_ids": option["price_ids"],
                                }
                            ],
                            "unresolved": [],
                        },
                        "clarification": None,
                    },
                )
            ]
        )

    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t06-{uuid4()}"
        receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "restart")
        async with research_worker(client, queue, engine, FunctionModel(model)):
            run_id = await TemporalResearchStarter(
                client, queue, workflow_type="ResearchWorkflowV2"
            ).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            waiting = await task_reaches(
                research, receipt.task_id, actor.id, {"needs_input", "failed"}
            )
            assert waiting.status == "needs_input" and waiting.question is not None
            question = waiting.question

        second_release = replace(
            first_release,
            id=uuid4(),
            published_at=first_release.published_at + timedelta(days=1),
        )
        CatalogStore(engine).publish(second_release)
        answer = ClarificationStore(engine).reserve_answer(
            actor.id,
            actor.generation,
            receipt.task_id,
            question.id,
            question.waiting_version,
            1,
            "version-answer",
            str(question.choices[1].id),
        )
        async with research_worker(client, queue, engine, FunctionModel(model)):
            handle = client.get_workflow_handle(receipt.workflow_id)
            accepted = await handle.execute_update(
                "answer", answer, id=str(answer.id), result_type=AnswerResult
            )
            assert accepted.acceptance == "accepted"
            report_id = await asyncio.wait_for(handle.result(), 20)
            assert research.task(receipt.task_id, actor.id).status == "completed"
            report = ReportStore(engine).read(actor.id, UUID(report_id))
            assert report is not None
            assert report.catalog_release_id == second_release.id
            assert lookup_calls == 2


async def test_time_skipped_question_deadline_closes_the_task(research_context):
    engine, research, (actor, _), plan = research_context
    CatalogStore(engine).publish(synthetic_versioned_release())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t06-expiry-{uuid4()}"
        async with research_worker(
            client, queue, engine, FunctionModel(clarifying_model)
        ):
            receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "expiry")
            run_id = await TemporalResearchStarter(
                client, queue, workflow_type="ResearchWorkflowV2"
            ).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            waiting = await task_reaches(
                research, receipt.task_id, actor.id, {"needs_input", "failed"}
            )
            assert waiting.status == "needs_input" and waiting.question is not None
            question = waiting.question
            await env.sleep(timedelta(days=7, seconds=1))
            assert (
                await asyncio.wait_for(
                    client.get_workflow_handle(receipt.workflow_id).result(), 10
                )
                == "expired"
            )
            expired = research.task(receipt.task_id, actor.id)
            assert expired.status == "failed"
            assert expired.error is not None and expired.error.code == "INPUT_EXPIRED"
            with pytest.raises(ValueError, match="QUESTION_CLOSED"):
                ClarificationStore(engine).reserve_answer(
                    actor.id,
                    actor.generation,
                    receipt.task_id,
                    question.id,
                    question.waiting_version,
                    1,
                    "too-late",
                    str(question.choices[1].id),
                )


async def test_answer_admitted_between_question_commit_and_wait_is_not_lost(
    research_context, monkeypatch
):
    engine, research, (actor, _), plan = research_context
    CatalogStore(engine).publish(synthetic_versioned_release())
    published = asyncio.Event()
    release_publish = asyncio.Event()

    original_publish = ResearchActivities.publish_question

    @activity.defn(name="whisky_publish_question_v1")
    async def held_publish(
        self: ResearchActivities, commit: QuestionCommit
    ) -> PublishedQuestion:
        commit = TypeAdapter(QuestionCommit).validate_python(commit)
        question = await original_publish(self, commit)
        published.set()
        await release_publish.wait()
        return question

    monkeypatch.setattr(ResearchActivities, "publish_question", held_publish)

    def model(messages, info):
        returns = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if not returns:
            return ModelResponse(parts=[ToolCallPart("search_reviewed_catalog", {})])
        if "Previously clarified: Question:" not in str(messages):
            return clarifying_model(messages, info)
        option = returns[-1].content
        if isinstance(option, str):
            option = json.loads(option)
        option = option[0]
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "report": {
                            "summary": "答覆在 wait 前已接受",
                            "candidates": [
                                {
                                    "release_id": option["release_id"],
                                    "item_id": option["item_id"],
                                    "claims": [option["facts"][0]],
                                    "reason": "來源與版本已核對",
                                    "price_ids": option["price_ids"],
                                }
                            ],
                            "unresolved": [],
                        },
                        "clarification": None,
                    },
                )
            ]
        )

    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t06-race-{uuid4()}"
        async with research_worker(client, queue, engine, FunctionModel(model)):
            receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "race")
            run_id = await TemporalResearchStarter(
                client, queue, workflow_type="ResearchWorkflowV2"
            ).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            await asyncio.wait_for(published.wait(), 10)
            waiting = research.task(receipt.task_id, actor.id)
            assert waiting.status == "needs_input" and waiting.question is not None
            question = waiting.question
            answer = ClarificationStore(engine).reserve_answer(
                actor.id,
                actor.generation,
                receipt.task_id,
                question.id,
                question.waiting_version,
                1,
                "race-answer",
                str(question.choices[1].id),
            )
            handle = client.get_workflow_handle(receipt.workflow_id)
            update = await handle.start_update(
                "answer",
                answer,
                id=str(answer.id),
                wait_for_stage=WorkflowUpdateStage.ACCEPTED,
                result_type=AnswerResult,
            )
            assert not release_publish.is_set()
            release_publish.set()
            assert (
                await asyncio.wait_for(update.result(), 15)
            ).acceptance == "accepted"
            report_id = await asyncio.wait_for(handle.result(), 20)
            assert research.task(receipt.task_id, actor.id).status == "completed"
            assert ReportStore(engine).read(actor.id, UUID(report_id)) is not None


async def test_different_worker_process_resumes_saved_question(research_context):
    engine, research, (actor, _), plan = research_context
    first_release = synthetic_versioned_release()
    CatalogStore(engine).publish(first_release)
    process_context = multiprocessing.get_context("spawn")

    async def start_process(address: str, namespace: str, queue: str):
        parent, child = process_context.Pipe()
        process = process_context.Process(
            target=run_worker,
            args=(address, namespace, queue, str(engine.url), child),
        )
        process.start()
        child.close()
        assert await asyncio.to_thread(parent.poll, 20), "worker did not start"
        assert parent.recv() == "ready"
        return process, parent

    async def stop_process(process, control):
        if process.is_alive():
            control.send("stop")
            await asyncio.to_thread(process.join, 15)
        if process.is_alive():
            process.terminate()
            await asyncio.to_thread(process.join, 5)
        control.close()
        assert process.exitcode == 0

    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t06-process-{uuid4()}"
        address = env.client.service_client.config.target_host
        first_process, first_control = await start_process(
            address, env.client.namespace, queue
        )
        try:
            receipt = research.reserve(
                actor.id, actor.generation, plan.id, 1, "process"
            )
            run_id = await TemporalResearchStarter(
                client, queue, workflow_type="ResearchWorkflowV2"
            ).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            waiting = await task_reaches(
                research, receipt.task_id, actor.id, {"needs_input", "failed"}
            )
            assert waiting.status == "needs_input" and waiting.question is not None
            question = waiting.question
        finally:
            await stop_process(first_process, first_control)

        second_release = replace(
            first_release,
            id=uuid4(),
            published_at=first_release.published_at + timedelta(days=1),
        )
        CatalogStore(engine).publish(second_release)
        answer = ClarificationStore(engine).reserve_answer(
            actor.id,
            actor.generation,
            receipt.task_id,
            question.id,
            question.waiting_version,
            1,
            "process-answer",
            str(question.choices[1].id),
        )
        second_process, second_control = await start_process(
            address, env.client.namespace, queue
        )
        try:
            handle = client.get_workflow_handle(receipt.workflow_id)
            accepted = await handle.execute_update(
                "answer", answer, id=str(answer.id), result_type=AnswerResult
            )
            assert accepted.acceptance == "accepted"
            report_id = await asyncio.wait_for(handle.result(), 20)
            report = ReportStore(engine).read(actor.id, UUID(report_id))
            assert report is not None
            assert report.catalog_release_id == second_release.id
            assert research.task(receipt.task_id, actor.id).status == "completed"
        finally:
            await stop_process(second_process, second_control)
