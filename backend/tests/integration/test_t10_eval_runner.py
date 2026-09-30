import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from whisky.bootstrap.worker import research_worker
from whisky.modules.catalog.publication import load_reviewed_release
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.research.quota import QuotaStore
from whisky.modules.research.source_reader import SourcePage

pytestmark = pytest.mark.integration
ROOT = Path(__file__).parents[3]


@pytest.fixture
def eval_runner(monkeypatch):
    for name in ("run_t08", "t10_inputs", "t10_source", "run_t10"):
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "backend/evals" / f"{name}.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "cause",
    [
        "ApplicationError: QuotaError: DAILY_BUDGET_EXHAUSTED",
        "ApplicationError: MODEL_DAILY_ALLOCATION_EXHAUSTED",
        "ModelHTTPError: status_code=429, cloudflare_code=3036",
    ],
)
def test_quota_stop_recognizes_nested_failures_despite_generic_task_error(
    eval_runner, cause
):
    assert eval_runner.quota_exhausted(
        {
            "error_code": "RESEARCH_FAILED",
            "failure_chain": ["WorkflowFailureError: Workflow execution failed", cause],
        }
    )


@pytest.mark.parametrize(
    "case_id, versions, expected",
    [
        ("expert_explicit_origin", [], False),
        ("expert_explicit_origin", ["f83aa51e-89e3-49fa-80d2-5f44d84cee3a"], True),
        ("hard_smoke_comparison", ["f83aa51e-89e3-49fa-80d2-5f44d84cee3a"], False),
        ("hard_smoke_comparison", [], True),
        ("strict_budget_empty", [], True),
        (
            "conditional_price_not_qualification",
            ["4e5c9aca-69d3-45fe-acc0-eb313c60b961"],
            False,
        ),
    ],
)
def test_case_candidate_gate_rejects_wrong_empty_or_forbidden_results(
    eval_runner, case_id, versions, expected
):
    from uuid import UUID

    report = SimpleNamespace(
        candidates=[
            SimpleNamespace(bottle_version_id=UUID(value)) for value in versions
        ]
    )
    assert eval_runner.case_candidate_gate(case_id, report) is expected
    assert not eval_runner.quota_exhausted(
        {
            "error_code": "RESEARCH_FAILED",
            "failure_chain": ["ModelHTTPError: status_code=429, cloudflare_code=3040"],
        }
    )


@pytest.mark.parametrize(
    "case_id",
    ["beginner_daily_food_clues", "strict_budget_empty", "hard_smoke_comparison"],
)
async def test_eval_runs_real_durable_boundaries_without_external_model_calls(
    research_context, eval_runner, case_id
):
    engine, *_ = research_context
    corpus = json.loads(eval_runner.CORPUS.read_text())
    controls = json.loads(eval_runner.CONTROLS.read_text())
    CatalogStore(engine).publish(
        load_reviewed_release((ROOT / corpus["catalog_manifest"]).read_text())
    )
    calls = []

    def model(messages, info):
        calls.append(info.output_tools[0].name)
        assert case_id == "beginner_daily_food_clues"
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "待使用者確認", "preferences": []},
                )
            ]
        )

    case = next(case for case in corpus["cases"] if case["id"] == case_id)
    typed = eval_runner.CaseControls.model_validate(controls["cases"][case_id])
    source_reader = eval_runner.EvalSourceReader()
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t10-runner-fixture-{uuid4()}"
        async with research_worker(
            client, queue, engine, FunctionModel(model), source_reader=source_reader
        ):
            result = await eval_runner.run_case(
                client, queue, engine, case, typed, source_reader
            )
    assert result["all_hard_gates_passed"], result
    assert result["source_reads"] == []
    assert result["failure_chain"] is None
    if case_id == "beginner_daily_food_clues":
        assert len(calls) == 1
        assert result["status"] == "needs_input"
        assert result["proposals"]
        assert "cleanup" in result
    else:
        assert calls == []
        assert result["status"] == "completed"
        assert result["report"]["candidates"] == []
        if case_id == "hard_smoke_comparison":
            from uuid import UUID

            from sqlalchemy import text

            from whisky.modules.research.restart_context_v4 import (
                read_restart_context_v4,
            )

            with engine.connect() as connection:
                row = connection.execute(
                    text("SELECT owner_id,plan_id FROM research_tasks WHERE id=:task"),
                    {"task": UUID(result["task_id"])},
                ).one()
            restart = read_restart_context_v4(
                engine, row.owner_id, row.plan_id, UUID(result["task_id"])
            )
            assert restart is not None
            assert restart.input.intent.smoke_comparison
            assert (
                restart.input.intent.origin_query
                == result["report"]["clarifiedBottle"]["name"]
            )
            assert restart.source_starting_bottle is not None
            assert (
                str(restart.source_starting_bottle.item_id)
                == "3e3c188d-6d45-4d28-8920-ed9377bde739"
            )


async def test_actual_quota_failure_is_detected_without_calling_provider(
    research_context, eval_runner
):
    engine, *_ = research_context
    corpus = json.loads(eval_runner.CORPUS.read_text())
    controls = json.loads(eval_runner.CONTROLS.read_text())
    CatalogStore(engine).publish(
        load_reviewed_release((ROOT / corpus["catalog_manifest"]).read_text())
    )
    case = next(c for c in corpus["cases"] if c["id"] == "beginner_daily_food_clues")
    typed = eval_runner.CaseControls.model_validate(controls["cases"][case["id"]])

    def forbidden_provider(messages, info):
        raise AssertionError("An unconfigured budget must not call the provider")

    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t10-quota-fixture-{uuid4()}"
        async with research_worker(
            client,
            queue,
            engine,
            FunctionModel(forbidden_provider),
            quota=QuotaStore(engine, daily_neuron_limit=0),
        ):
            result = await eval_runner.run_case(
                client, queue, engine, case, typed, eval_runner.EvalSourceReader()
            )
    assert result["status"] == "failed"
    assert result["error_code"] == "RESEARCH_FAILED"
    assert result["provider_attempts"] == 0
    assert eval_runner.quota_exhausted(result), result["failure_chain"]


async def test_source_selection_receives_the_actual_research_goal(
    research_context, eval_runner
):
    engine, *_ = research_context
    corpus = json.loads(eval_runner.CORPUS.read_text())
    controls = json.loads(eval_runner.CONTROLS.read_text())
    CatalogStore(engine).publish(
        load_reviewed_release((ROOT / corpus["catalog_manifest"]).read_text())
    )
    case = next(c for c in corpus["cases"] if c["id"] == "source_failure_fallback")
    typed = eval_runner.CaseControls.model_validate(controls["cases"][case["id"]])
    prompts = []

    def model(messages, info):
        prompt = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        )
        payload = json.loads(prompt[prompt.index("{") :])
        prompts.append(payload)
        assert payload.get("goal") == case["input"]
        choice = next(
            source
            for source in payload["provided_sources"]
            if source["item_name"] == "格蘭利威 12 年"
        )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name, {"source_index": choice["index"]}
                )
            ]
        )

    class FixtureSource:
        async def read(self, url):
            return SourcePage(
                url, "Explicit synthetic source fixture; not reviewed facts."
            )

    source_reader = eval_runner.EvalSourceReader(delegate=FixtureSource())
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t10-goal-fixture-{uuid4()}"
        async with research_worker(
            client, queue, engine, FunctionModel(model), source_reader=source_reader
        ):
            result = await eval_runner.run_case(
                client, queue, engine, case, typed, source_reader
            )
    assert result["status"] == "completed", result["failure_chain"]
    assert len(prompts) == 1
    assert result["source_reads"][0]["status"] == "ok"
