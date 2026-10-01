"""Run frozen T10 controls through V4 workflows in an isolated loopback DB.

No credentials are required for --dry-run. Live runs use the same model, quota,
source reader and durable worker as the product. Public results exclude reasoning.
"""

import argparse
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from run_t08 import (
    failure_chain,
    isolated_database,
    source_observation_summary,
    usage_summary,
)
from sqlalchemy import create_engine
from t10_inputs import CaseControls, select_answer, validated_cases
from t10_source import EvalSourceReader
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from whisky.bootstrap.migrate import upgrade
from whisky.bootstrap.worker import (
    cloudflare_model,
    cloudflare_token_from_values,
    research_worker,
)
from whisky.modules.catalog.public import (
    current_release_id,
    reviewed_flavor_references,
    search_reviewed_candidates,
)
from whisky.modules.catalog.publication import load_reviewed_release
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.proposal import ReviewedFlavorMapping
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.store import IdentityStore
from whisky.modules.identity.tokens import Principal
from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.contracts import AnswerResult
from whisky.modules.research.inputs_v4 import StartCommandV4, StartTurnV4
from whisky.modules.research.proposal_view_v4 import read_preference_proposal_v4
from whisky.modules.research.quota import QuotaStore
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.store import ResearchStore
from whisky.modules.research.workflow_v4 import ResearchWorkflowV4

ROOT = Path(__file__).resolve().parents[2]
CORPUS = Path(__file__).with_name("t10_cases.v1.json")
CONTROLS = Path(__file__).with_name("t10_inputs.v1.json")


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quota_exhausted(result):
    reasons = {
        "MODEL_DAILY_ALLOCATION_EXHAUSTED",
        "DAILY_BUDGET_EXHAUSTED",
        "DAILY_BUDGET_UNCONFIGURED",
    }
    return result.get("error_code") in reasons or any(
        reason in cause or "cloudflare_code=3036" in cause
        for cause in result.get("failure_chain") or []
        for reason in reasons
    )


def case_candidate_gate(case_id, report):
    if report is None:
        return False
    versions = [candidate.bottle_version_id for candidate in report.candidates]
    if case_id == "expert_explicit_origin":
        return versions == [UUID("f83aa51e-89e3-49fa-80d2-5f44d84cee3a")]
    if case_id in {"hard_smoke_comparison", "strict_budget_empty", "unlisted_origin"}:
        return not versions
    if case_id == "conditional_price_not_qualification":
        return UUID("4e5c9aca-69d3-45fe-acc0-eb313c60b961") not in versions
    return True


def snapshot(corpus, controls, quota, results, inject_first=False):
    return {
        "corpus_version": corpus["version"],
        "controls_version": controls["version"],
        "corpus_sha256": fingerprint(CORPUS),
        "controls_sha256": fingerprint(CONTROLS),
        "catalog_manifest_sha256": fingerprint(ROOT / corpus["catalog_manifest"]),
        "model": corpus["model"],
        "scope": "real V4 workflow samples; provider attempts counted separately",
        "daily_neuron_allowance": quota.daily_neuron_limit,
        "daily_reserved_neurons": quota.daily_reserved_neurons(),
        "provider_attempts": sum(result["provider_attempts"] for result in results),
        "source_failure_mode": "single explicitly marked fault injection"
        if inject_first
        else "real network only",
        "human_rubric_status": "pending",
        "results": results,
    }


async def run_case(client, queue, engine, case, controls, source_reader):
    case_id = case["id"]
    actor = IdentityStore(engine).resolve(
        Principal("https://whisky-eval.example/", f"t10-{case_id}-{uuid4()}")
    )
    plan = PlanStore(engine).create(
        actor.id, actor.generation, f"T10 {case_id}", controls.conditions
    )
    research = ResearchStore(engine)
    turn = StartTurnV4(
        uuid4(),
        uuid4(),
        StartCommandV4(
            type="start_v4",
            key=f"eval-{case_id}",
            planId=plan.id,
            conditionsRevision=1,
            input=controls.input,
        ),
    )
    receipt = research.reserve_turn_v4(actor.id, actor.generation, turn)
    if source_reader.inject_first and case_id == "source_failure_fallback":
        source_reader.fail_first_workflows.add(receipt.workflow_id)
    handle = await client.start_workflow(
        ResearchWorkflowV4.run,
        str(receipt.task_id),
        id=receipt.workflow_id,
        task_queue=queue,
    )
    research.confirm(
        actor.id, actor.generation, receipt.id, handle.first_execution_run_id
    )
    started = time.perf_counter()
    questions = []
    proposals = []
    answered = set()
    failure = None
    try:
        async with asyncio.timeout(240):
            while True:
                view = research.task(receipt.task_id, actor.id)
                if view is None:
                    raise ValueError("EVAL_TASK_MISSING")
                if view.status in {"completed", "failed", "cancelled", "superseded"}:
                    break
                if (
                    view.status == "needs_input"
                    and view.question is not None
                    and view.question.id not in answered
                ):
                    question = view.question
                    draft = read_preference_proposal_v4(
                        engine, actor.id, receipt.task_id
                    )
                    questions.append(question.model_dump(mode="json", by_alias=True))
                    if draft is not None:
                        proposals.append(draft.model_dump(mode="json", by_alias=True))
                    choice = select_answer(
                        receipt.task_id, question, draft is not None, controls
                    )
                    if choice is None:
                        break
                    answer = ClarificationStore(engine).reserve_answer(
                        actor.id,
                        actor.generation,
                        receipt.task_id,
                        question.id,
                        question.waiting_version,
                        1,
                        f"eval-answer-{question.waiting_version}",
                        str(choice),
                    )
                    accepted = await handle.execute_update(
                        "answer", answer, id=str(answer.id), result_type=AnswerResult
                    )
                    if accepted.acceptance != "accepted":
                        raise ValueError("EVAL_ANSWER_REJECTED")
                    answered.add(question.id)
                await asyncio.sleep(0.2)
    except Exception as error:
        failure = failure_chain(error)
        view = research.task(receipt.task_id, actor.id)
    report = (
        ReportStore(engine).read(actor.id, view.report_id)
        if view is not None and view.report_id is not None
        else None
    )
    comparison = (
        ReportStore(engine).read_comparison_v4(actor.id, report.id)
        if report is not None
        else None
    )
    other = IdentityStore(engine).resolve(
        Principal("https://whisky-eval.example/", f"t10-other-{uuid4()}")
    )
    current = PlanStore(engine).read(plan.id, actor.id)
    eligible = (
        {
            candidate.item.id: candidate
            for candidate in search_reviewed_candidates(
                engine, report.evaluated_on, controls.conditions.budget_twd
            )
        }
        if report is not None
        else {}
    )
    expected_wait = controls.stop_at == "proposal_question"
    gates = {
        "expected_outcome": failure is None
        and view is not None
        and (
            view.status == "needs_input" and bool(proposals)
            if expected_wait
            else view.status == "completed" and report is not None
        ),
        "owner_isolation": research.task(receipt.task_id, other.id) is None
        and (report is None or ReportStore(engine).read(other.id, report.id) is None),
        "conditions_not_changed_by_model": current is not None
        and current.conditions == controls.conditions
        and current.conditions_revision == 1,
        "at_most_three_candidates": report is None
        if expected_wait
        else report is not None and len(report.candidates) <= 3,
        "qualified_catalog_candidates": expected_wait
        or report is not None
        and all(
            item.item_id in eligible and item.release_id == report.catalog_release_id
            for item in report.candidates
        ),
        "comparison_atomically_available": expected_wait
        or report is not None
        and comparison is not None,
    }
    if not expected_wait:
        gates["case_candidate_expectation"] = case_candidate_gate(case_id, report)
    if controls.version_choice is not None:
        gates["exact_origin_confirmed_before_report"] = (
            report is not None
            and report.clarified_bottle is not None
            and report.clarified_bottle.reviewed_in_release
            and report.clarified_bottle.bottle_version_id == controls.version_choice
            and any(
                str(controls.version_choice)
                in {choice["id"] for choice in q["choices"]}
                for q in questions
            )
        )
    if case_id == "expert_generic_name":
        gates["complete_reviewed_version_choices"] = any(
            {choice["id"] for choice in q["choices"]}
            == {
                "dd506fdd-c680-41bc-bbd3-ec9490474a49",
                "4e5c9aca-69d3-45fe-acc0-eb313c60b961",
            }
            for q in questions
        )
    if proposals:
        with engine.connect() as connection:
            mappings = tuple(
                ReviewedFlavorMapping(
                    feature_key=ref.label,
                    reference={"release_id": ref.release_id, "item_id": ref.item_id},
                    evidence_ids=ref.evidence_ids,
                )
                for ref in reviewed_flavor_references(
                    connection, current_release_id(connection)
                )
            )
        for raw in proposals:
            from whisky.modules.research.proposal_view_v4 import (
                PreferenceProposalViewV4,
            )

            draft = PreferenceProposalViewV4.model_validate(raw)
            draft.proposal.validate_source(draft.source_text)
            draft.proposal.validate_mappings(mappings, require_mapping=True)
        gates["proposal_quotes_and_reviewed_mappings"] = True
    if view is not None and view.status == "failed":
        try:
            await handle.result()
        except Exception as error:
            failure = failure_chain(error)
    usage = usage_summary(engine, receipt.task_id)
    observations = source_observation_summary(engine, receipt.task_id)
    calls = source_reader.calls.get(receipt.workflow_id, [])
    gates["source_observations_unreviewed"] = all(
        row["review_status"] == "unreviewed" for row in observations
    )
    if source_reader.inject_first and case_id == "source_failure_fallback":
        gates["bounded_failure_then_real_alternative"] = (
            len(calls) == 2
            and calls[0].get("fault_injection") is True
            and calls[1]["status"] == "ok"
            and calls[0]["url"] != calls[1]["url"]
            and len(observations) == 2
        )
    public_observations = json.loads(json.dumps(observations, default=str))
    result = {
        "case_id": case_id,
        "status": view.status if view is not None else "missing",
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "input": controls.input.model_dump(mode="json", by_alias=True),
        "initial_conditions": controls.conditions.model_dump(mode="json"),
        "task_id": str(receipt.task_id),
        "questions": questions,
        "proposals": proposals,
        "report": report.model_dump(mode="json", by_alias=True)
        if report is not None
        else None,
        "comparison": comparison.model_dump(mode="json", by_alias=True)
        if comparison is not None
        else None,
        "hard_gates": gates,
        "all_hard_gates_passed": all(gates.values()),
        "usage": usage,
        "provider_attempts": sum(
            int(row["attempts"]) for row in usage if row["kind"] == "model"
        ),
        "source_reads": source_reader.calls.get(receipt.workflow_id, []),
        "source_observations": public_observations,
        "error_code": view.error.code
        if view is not None and view.error is not None
        else None,
        "failure_chain": failure,
    }
    if view is not None and view.status not in {
        "completed",
        "failed",
        "cancelled",
        "superseded",
    }:
        await handle.cancel()
        result["cleanup"] = (
            "cancelled after capturing the designated confirmation boundary"
        )
    return result


async def run_all(
    engine,
    corpus,
    controls,
    token,
    account,
    daily_neurons,
    selected,
    output,
    inject_first=False,
):
    release = load_reviewed_release((ROOT / corpus["catalog_manifest"]).read_text())
    CatalogStore(engine).publish(release)
    quota = QuotaStore(
        engine, daily_neuron_limit=daily_neurons, model_name=corpus["model"]
    )
    source_reader = EvalSourceReader(inject_first=inject_first)
    results = []
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-t10-eval-{uuid4()}"
        async with research_worker(
            client,
            queue,
            engine,
            cloudflare_model(account, token, model_name=corpus["model"]),
            quota=quota,
            source_reader=source_reader,
        ):
            for case in corpus["cases"]:
                if selected is not None and case["id"] not in selected:
                    continue
                typed = CaseControls.model_validate(controls["cases"][case["id"]])
                for repetition in range(1, corpus["runs_per_case"] + 1):
                    result = await run_case(
                        client, queue, engine, case, typed, source_reader
                    )
                    result["repetition"] = repetition
                    results.append(result)
                    output.write_text(
                        json.dumps(
                            snapshot(corpus, controls, quota, results, inject_first),
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                    print(
                        f"{case['id']} #{repetition}: {result['status']} "
                        f"{result['elapsed_ms']}ms "
                        f"gates={result['all_hard_gates_passed']}",
                        flush=True,
                    )
                    if quota_exhausted(result):
                        return snapshot(corpus, controls, quota, results, inject_first)
    return snapshot(corpus, controls, quota, results, inject_first)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--inject-source-failure",
        action="store_true",
        help="inject one marked failure only for the source-fallback case",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", action="append")
    args = parser.parse_args()
    corpus = json.loads(CORPUS.read_text())
    controls = json.loads(CONTROLS.read_text())
    prepared = validated_cases(corpus, controls)
    selected = set(args.case) if args.case else None
    if selected is not None and not selected <= set(prepared):
        raise SystemExit("EVAL_INPUT_UNKNOWN_CASE")
    if args.dry_run:
        count = len(selected) if selected is not None else len(prepared)
        print(
            json.dumps(
                {
                    "case_count": count,
                    "workflow_runs": count * corpus["runs_per_case"],
                    "corpus_sha256": fingerprint(CORPUS),
                    "controls_sha256": fingerprint(CONTROLS),
                    "model_calls": 0,
                }
            )
        )
        return
    if args.output is None:
        parser.error("live eval requires --output")
    if args.output.exists():
        parser.error("output already exists; retain the previous evidence")
    token = cloudflare_token_from_values(os.environ)
    account = os.environ["WHISKY_CLOUDFLARE_ACCOUNT_ID"]
    daily_neurons = int(os.environ["WHISKY_DAILY_MODEL_NEURONS"])
    base_url = os.environ["WHISKY_TEST_POSTGRES_URL"]
    database_url, database_name = isolated_database(base_url)
    admin_url = base_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )
    engine = create_engine(database_url)
    try:
        upgrade(engine, ROOT / "backend/migrations")
        output = asyncio.run(
            run_all(
                engine,
                corpus,
                controls,
                token,
                account,
                daily_neurons,
                selected,
                args.output,
                args.inject_source_failure,
            )
        )
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        expected = (len(selected) if selected is not None else len(prepared)) * corpus[
            "runs_per_case"
        ]
        if len(output["results"]) != expected or any(
            not result["all_hard_gates_passed"] for result in output["results"]
        ):
            raise SystemExit("Live eval has incomplete samples or failed hard gates")
    finally:
        engine.dispose()
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name))
            )


if __name__ == "__main__":
    main()
