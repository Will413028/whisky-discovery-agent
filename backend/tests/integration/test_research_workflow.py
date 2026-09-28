"""A controlled model exercises the real Temporal/PydanticAI/DB path."""

import asyncio
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.messages import (
    ModelResponse,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import text
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from test_catalog_release import synthetic_release

from whisky.bootstrap.worker import research_worker
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.research import agent as agent_module
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.temporal_start import TemporalResearchStarter

pytestmark = pytest.mark.integration


def controlled_model(messages, info, expected_options=1):
    returns = [
        part
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    if not returns:
        assert [tool.name for tool in info.function_tools] == [
            "search_reviewed_catalog"
        ]
        return ModelResponse(parts=[ToolCallPart("search_reviewed_catalog", {})])
    options = returns[-1].content
    if isinstance(options, str):
        options = json.loads(options)
    assert len(options) == expected_options
    option = options[0]
    assert option["facts"] and option["evidence_ids"]
    assert len(info.output_tools) == 1
    return ModelResponse(
        parts=[
            ToolCallPart(
                info.output_tools[0].name,
                {
                    "summary": "已依 reviewed catalog 查核",
                    "candidates": [
                        {
                            "release_id": option["release_id"],
                            "item_id": option["item_id"],
                            "claims": [option["facts"][0]],
                            "reason": "官方事實與版本相符",
                            "price_ids": option["price_ids"],
                        }
                    ],
                    "unresolved": [],
                },
            )
        ]
    )


async def test_controlled_agent_uses_catalog_tool_and_commits_report(research_context):
    engine, research, (actor, _), plan = research_context
    release = synthetic_release()
    CatalogStore(engine).publish(release)
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t05-{uuid4()}"
        async with research_worker(
            client, queue, engine, FunctionModel(controlled_model)
        ):
            receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "agent")
            run_id = await TemporalResearchStarter(client, queue).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            handle = client.get_workflow_handle(receipt.workflow_id)
            report_id = await asyncio.wait_for(handle.result(), timeout=20)
            view = research.task(receipt.task_id, actor.id)
            assert view.status == "completed"
            assert str(view.report_id) == report_id
            assert view.view_version >= 3
            history = await handle.fetch_history()
            activities = [
                event.activity_task_scheduled_event_attributes.activity_type.name
                for event in history.events
                if event.HasField("activity_task_scheduled_event_attributes")
            ]
            assert sum("model_request" in name for name in activities) == 2
            assert any("reviewed_catalog_v1" in name for name in activities), activities
            assert "whisky_save_report_v1" in activities


async def test_catalog_tool_exposes_every_reviewed_item_after_twenty(research_context):
    engine, research, (actor, _), plan = research_context
    release = synthetic_release()
    first_item = release.items[0]
    first_evidence = release.evidence[0]
    items = [first_item]
    evidence = [first_evidence]
    for _ in range(20):
        bottle_id = uuid4()
        evidence_id = uuid4()
        evidence.append(
            replace(
                first_evidence,
                id=evidence_id,
                source_id=uuid4(),
                bottle_version_id=bottle_id,
            )
        )
        items.append(
            replace(
                first_item,
                id=uuid4(),
                bottle=replace(first_item.bottle, version_id=bottle_id),
                facts=tuple(
                    replace(fact, evidence_ids=(evidence_id,))
                    for fact in first_item.facts
                ),
                flavor_tags=tuple(
                    replace(tag, evidence_ids=(evidence_id,))
                    for tag in first_item.flavor_tags
                ),
            )
        )
    CatalogStore(engine).publish(
        replace(release, items=tuple(items), evidence=tuple(evidence))
    )

    def expect_all_options(messages, info):
        return controlled_model(messages, info, expected_options=21)

    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t05-{uuid4()}"
        async with research_worker(
            client, queue, engine, FunctionModel(expect_all_options)
        ):
            receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "all")
            run_id = await TemporalResearchStarter(client, queue).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            await asyncio.wait_for(
                client.get_workflow_handle(receipt.workflow_id).result(), timeout=20
            )
            assert research.task(receipt.task_id, actor.id).status == "completed"


async def test_report_commit_survives_lost_activity_completion(
    research_context, monkeypatch
):
    engine, research, (actor, _), plan = research_context
    CatalogStore(engine).publish(synthetic_release())
    model_calls = 0

    def counting_model(messages, info):
        nonlocal model_calls
        model_calls += 1
        return controlled_model(messages, info)

    original_save = ReportStore.save
    save_calls = 0

    def lose_first_completion(self, *args, **kwargs):
        nonlocal save_calls
        saved = original_save(self, *args, **kwargs)
        save_calls += 1
        if save_calls == 1:
            raise RuntimeError("injected after report commit")
        return saved

    monkeypatch.setattr(ReportStore, "save", lose_first_completion)
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t05-{uuid4()}"
        async with research_worker(
            client, queue, engine, FunctionModel(counting_model)
        ):
            receipt = research.reserve(
                actor.id, actor.generation, plan.id, 1, "lost-report"
            )
            run_id = await TemporalResearchStarter(client, queue).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            report_id = await asyncio.wait_for(
                client.get_workflow_handle(receipt.workflow_id).result(), timeout=20
            )
            assert str(research.task(receipt.task_id, actor.id).report_id) == report_id
            assert save_calls == 2
            assert model_calls == 2
            with engine.connect() as connection:
                assert (
                    connection.scalar(text("SELECT count(*) FROM research_reports"))
                    == 1
                )


async def test_worker_restart_replays_completed_catalog_tool_without_rerun(
    research_context, monkeypatch
):
    engine, research, (actor, _), plan = research_context
    CatalogStore(engine).publish(synthetic_release())
    real_search = agent_module.search_reviewed_candidates
    search_calls = 0

    def count_search(*args):
        nonlocal search_calls
        search_calls += 1
        return real_search(*args)

    monkeypatch.setattr(agent_module, "search_reviewed_candidates", count_search)
    second_model_started = asyncio.Event()

    async def held_model(messages, info):
        if not any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        ):
            return controlled_model(messages, info)
        second_model_started.set()
        await asyncio.Future()

    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t05-{uuid4()}"
        first_worker = research_worker(client, queue, engine, FunctionModel(held_model))
        async with first_worker:
            receipt = research.reserve(
                actor.id, actor.generation, plan.id, 1, "restart"
            )
            run_id = await TemporalResearchStarter(client, queue).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            await asyncio.wait_for(second_model_started.wait(), timeout=20)
            assert search_calls == 1
        async with research_worker(
            client, queue, engine, FunctionModel(controlled_model)
        ):
            await asyncio.wait_for(
                client.get_workflow_handle(receipt.workflow_id).result(), timeout=20
            )
            assert search_calls == 1
            assert research.task(receipt.task_id, actor.id).status == "completed"


async def test_invalid_agent_result_finishes_task_as_failed(research_context):
    engine, research, (actor, _), plan = research_context
    CatalogStore(engine).publish(synthetic_release())

    def invalid_result(messages, info):
        response = controlled_model(messages, info)
        if any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        ):
            response.parts[0].args["candidates"][0]["claims"][0]["value"] = (
                "捏造的來源事實"
            )
        return response

    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t05-{uuid4()}"
        async with research_worker(
            client, queue, engine, FunctionModel(invalid_result)
        ):
            receipt = research.reserve(
                actor.id, actor.generation, plan.id, 1, "invalid"
            )
            run_id = await TemporalResearchStarter(client, queue).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            with pytest.raises(Exception):
                await asyncio.wait_for(
                    client.get_workflow_handle(receipt.workflow_id).result(),
                    timeout=20,
                )
            task = research.task(receipt.task_id, actor.id)
            assert task.status == "failed"
            assert task.report_id is None
            assert task.error is not None
            assert task.error.code == "RESEARCH_FAILED"


async def test_model_cannot_complete_empty_report_without_catalog_tool(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    CatalogStore(engine).publish(synthetic_release())

    def skip_catalog(_messages, info):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "summary": "沒有符合條件的酒款",
                        "candidates": [],
                        "unresolved": [],
                    },
                )
            ]
        )

    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t05-{uuid4()}"
        async with research_worker(client, queue, engine, FunctionModel(skip_catalog)):
            receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "skip")
            run_id = await TemporalResearchStarter(client, queue).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            with pytest.raises(Exception):
                await asyncio.wait_for(
                    client.get_workflow_handle(receipt.workflow_id).result(),
                    timeout=20,
                )
            task = research.task(receipt.task_id, actor.id)
            assert task.status == "failed"
            with engine.connect() as connection:
                assert (
                    connection.scalar(text("SELECT count(*) FROM research_reports"))
                    == 0
                )


async def test_hidden_model_thinking_never_enters_temporal_history(research_context):
    engine, research, (actor, _), plan = research_context
    CatalogStore(engine).publish(synthetic_release())
    hidden = "private-thinking-must-not-be-persisted"

    def thinking_model(messages, info):
        response = controlled_model(messages, info)
        return replace(response, parts=(ThinkingPart(hidden), *response.parts))

    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t05-{uuid4()}"
        async with research_worker(
            client, queue, engine, FunctionModel(thinking_model)
        ):
            receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "hidden")
            run_id = await TemporalResearchStarter(client, queue).start(receipt.task_id)
            research.confirm(actor.id, actor.generation, receipt.id, run_id)
            handle = client.get_workflow_handle(receipt.workflow_id)
            await asyncio.wait_for(handle.result(), timeout=20)
            history = await handle.fetch_history()
            decoded = []
            for event in history.events:
                if event.HasField("activity_task_completed_event_attributes"):
                    payloads = (
                        event.activity_task_completed_event_attributes.result.payloads
                    )
                    decoded.extend(await client.data_converter.decode(payloads))
            assert hidden not in repr(decoded)
