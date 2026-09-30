import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import text
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)
from test_catalog_release import synthetic_release

from whisky.bootstrap.worker import research_worker
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.store import PlanStore
from whisky.modules.research.agent_v4 import configure_research_agents_v4
from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.contracts import AnswerResult
from whisky.modules.research.inputs_v4 import (
    ResearchInputV4,
    StartCommandV4,
    StartTurnV4,
)
from whisky.modules.research.quota import QuotaStore
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.source_reader import SourceReader
from whisky.modules.research.workflow_v4 import ResearchWorkflowV4

pytestmark = pytest.mark.integration


def proposal_model(messages, info):
    return ModelResponse(
        parts=[
            ToolCallPart(
                info.output_tools[0].name,
                {
                    "summary": "甜香只是待確認線索",
                    "preferences": [
                        {
                            "description": "甜香",
                            "intent": "prefer",
                            "source_quote": "喜歡甜點",
                            "source_kind": "food_clue",
                        }
                    ],
                },
            )
        ]
    )


async def test_model_proposal_becomes_a_durable_question_without_changing_conditions(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    source = "我喜歡甜點，還不知道喜歡哪種威士忌"
    turn = StartTurnV4(
        uuid4(),
        uuid4(),
        StartCommandV4(
            type="start_v4",
            key="durable-proposal",
            plan_id=plan.id,
            conditions_revision=1,
            input=ResearchInputV4(phase="proposal", source_text=source),
        ),
    )
    receipt = research.reserve_turn_v4(actor.id, actor.generation, turn)
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t10-v4-{uuid4()}"
        async with research_worker(
            client, queue, engine, FunctionModel(proposal_model)
        ):
            handle = await client.start_workflow(
                ResearchWorkflowV4.run,
                str(receipt.task_id),
                id=receipt.workflow_id,
                task_queue=queue,
            )
            async with asyncio.timeout(15):
                while True:
                    view = research.task(receipt.task_id, actor.id)
                    state = await handle.describe()
                    if (
                        view.status in {"needs_input", "failed"}
                        or state.status != WorkflowExecutionStatus.RUNNING
                    ):
                        break
                    await asyncio.sleep(0.05)
            assert view.status == "needs_input"
            assert view.question is not None
            assert "偏好仍未確認" in view.question.prompt
            assert (
                PlanStore(engine).read(plan.id, actor.id).conditions == plan.conditions
            )
            await handle.cancel()


@pytest.mark.parametrize(
    "origin_query, choice, expected_candidates",
    [
        (None, 0, 1),
        ("不在庫中的版本", 0, 0),
        ("不在庫中的版本", 1, 1),
    ],
)
async def test_proposal_restart_keeps_question_and_unconfirmed_preferences(
    research_context,
    origin_query,
    choice,
    expected_candidates,
):
    engine, research, (actor, _), plan = research_context
    release = synthetic_release()
    evidence = replace(
        release.evidence[0], url="https://www.drinks.com.tw/product.aspx?Id=1753"
    )
    CatalogStore(engine).publish(replace(release, evidence=(evidence,)))
    calls = {"proposal": 0, "source": 0}

    def model(messages, info):
        if "preferences" in info.output_tools[0].parameters_json_schema["properties"]:
            calls["proposal"] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "summary": "甜香只是待確認線索",
                            "intent": {"origin_query": origin_query},
                            "preferences": [
                                {
                                    "description": "甜香",
                                    "intent": "prefer",
                                    "source_quote": "喜歡甜點",
                                    "source_kind": "food_clue",
                                }
                            ],
                        },
                    )
                ]
            )
        calls["source"] += 1
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"source_index": 1})]
        )

    async def fetch(url, byte_limit):
        return 200, {"Content-Type": "text/html"}, b"<html>synthetic test source</html>"

    source_reader = SourceReader(fetch=fetch)
    quota = QuotaStore(engine, daily_neuron_limit=1000)
    receipt = research.reserve_turn_v4(
        actor.id,
        actor.generation,
        StartTurnV4(
            uuid4(),
            uuid4(),
            StartCommandV4(
                type="start_v4",
                key="restart-proposal",
                plan_id=plan.id,
                conditions_revision=1,
                input=ResearchInputV4(phase="proposal", source_text="我喜歡甜點"),
            ),
        ),
    )
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t10-restart-{uuid4()}"
        async with research_worker(
            client,
            queue,
            engine,
            FunctionModel(model),
            source_reader=source_reader,
            quota=quota,
        ):
            handle = await client.start_workflow(
                ResearchWorkflowV4.run,
                str(receipt.task_id),
                id=receipt.workflow_id,
                task_queue=queue,
            )
            research.confirm(
                actor.id, actor.generation, receipt.id, handle.result_run_id
            )
            async with asyncio.timeout(15):
                while research.task(receipt.task_id, actor.id).status not in {
                    "needs_input",
                    "failed",
                }:
                    await asyncio.sleep(0.05)
            waiting = research.task(receipt.task_id, actor.id)
            assert waiting.status == "needs_input"
        reopened = research.task(receipt.task_id, actor.id)
        assert reopened.question == waiting.question
        assert calls == {"proposal": 1, "source": 0}
        async with research_worker(
            client,
            queue,
            engine,
            FunctionModel(model),
            source_reader=source_reader,
            quota=quota,
        ):
            answer = ClarificationStore(engine).reserve_answer(
                actor.id,
                actor.generation,
                receipt.task_id,
                waiting.question.id,
                waiting.conditions_revision,
                waiting.question.waiting_version,
                "use-intent",
                str(waiting.question.choices[choice].id),
            )
            result = await handle.execute_update(
                "answer", answer, id=str(answer.id), result_type=AnswerResult
            )
            assert result.acceptance == "accepted"
            report_id = await asyncio.wait_for(handle.result(), timeout=30)
        history = await handle.fetch_history()
    report = ReportStore(engine).read(actor.id, report_id)
    assert report.clarified_bottle is None
    assert len(report.candidates) == expected_candidates
    assert calls == {"proposal": 1, "source": expected_candidates}
    assert PlanStore(engine).read(plan.id, actor.id).conditions == plan.conditions
    with engine.connect() as connection:
        usage = connection.execute(
            text(
                "SELECT kind,status,count(*) FROM research_usage_attempts "
                "WHERE task_id=:task GROUP BY kind,status"
            ),
            dict(task=receipt.task_id),
        ).all()
    expected_usage = [("model", "completed", 1 + expected_candidates)]
    if expected_candidates:
        expected_usage.append(("reader", "completed", 1))
    assert sorted(usage) == expected_usage

    def forbidden_model(messages, info):
        raise AssertionError("History replay invoked a provider")

    configure_research_agents_v4(FunctionModel(forbidden_model))
    replayer = Replayer(
        workflows=[ResearchWorkflowV4],
        plugins=[PydanticAIPlugin()],
        workflow_runner=SandboxedWorkflowRunner(
            restrictions=SandboxRestrictions.default.with_passthrough_modules(
                "whisky.modules.research.agent_v4",
                "whisky.modules.research.proposal_agent_v4",
            )
        ),
    )
    await replayer.replay_workflow(history)
