"""Run the frozen T08 corpus against the real Workers AI model in isolation.

Requires a dedicated loopback PostgreSQL fixture URL and explicit model allowance.
Only source, result and usage summaries are saved; credentials and reasoning are not.
"""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.exceptions import ModelHTTPError
from sqlalchemy import Engine, create_engine, text
from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from whisky.bootstrap.migrate import upgrade
from whisky.bootstrap.worker import WORKERS_AI_MODEL, cloudflare_model, research_worker
from whisky.modules.catalog.public import published_source, search_reviewed_candidates
from whisky.modules.catalog.publication import load_reviewed_release
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.store import IdentityStore
from whisky.modules.identity.tokens import Principal
from whisky.modules.research.agent_v3 import PROMPT_VERSION_V3
from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.contracts import AnswerResult
from whisky.modules.research.quota import MODEL_NEURON_RATES, QuotaStore
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.source_reader import (
    SourcePage,
    SourceReader,
    SourceReadError,
)
from whisky.modules.research.store import ResearchStore
from whisky.modules.research.temporal_start import TemporalResearchStarter

ROOT = Path(__file__).resolve().parents[2]
CORPUS = Path(__file__).with_name("t08_cases.v1.json")


class TracedSourceReader(SourceReader):
    """Record public source choices for the manual tool-choice rubric."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: dict[str, list[dict[str, str]]] = {}

    async def read(self, url: str) -> SourcePage:
        workflow_id = activity.info().workflow_id
        try:
            page = await super().read(url)
        except SourceReadError as error:
            self.calls.setdefault(workflow_id, []).append(
                {"url": url, "status": "unavailable", "code": error.code}
            )
            raise
        self.calls.setdefault(workflow_id, []).append(
            {"url": url, "status": "ok", "final_url": page.final_url}
        )
        return page


def isolated_database(base_url: str) -> tuple[str, str]:
    if not base_url.startswith("postgresql+psycopg://postgres@127.0.0.1:"):
        raise ValueError("Live eval requires a dedicated loopback PostgreSQL fixture")
    if not base_url.endswith("/whisky_test"):
        raise ValueError("Live eval fixture must be whisky_test")
    name = f"whisky_eval_{uuid4().hex}"
    return base_url.rsplit("/", 1)[0] + "/" + name, name


def usage_summary(engine: Engine, task_id: UUID) -> list[dict[str, object]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
            SELECT kind,status,count(*) AS attempts,
                   coalesce(sum(reserved_neurons),0) AS reserved_neurons,
                   coalesce(sum(reserved_input_tokens),0) AS reserved_input_upper_bound,
                   coalesce(sum(reserved_output_tokens),0) AS reserved_output_tokens,
                   coalesce(sum(actual_input_tokens),0) AS input_tokens,
                   coalesce(sum(actual_output_tokens),0) AS output_tokens,
                   coalesce(sum(latency_ms),0) AS latency_ms
            FROM research_usage_attempts WHERE task_id=:task
            GROUP BY kind,status ORDER BY kind,status
            """),
            dict(task=task_id),
        ).mappings()
        return [dict(row) for row in rows]


def source_observation_summary(
    engine: Engine, task_id: UUID
) -> list[dict[str, object]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
            SELECT id,release_id,bottle_version_id,evidence_id,status,review_status,
                   error_code,content_sha256,length(visible_text) AS text_length,
                   effective_url,source_checked_on,observed_at
            FROM research_source_observations WHERE task_id=:task
            ORDER BY observed_at
            """),
            dict(task=task_id),
        ).mappings()
        return [dict(row) for row in rows]


def failure_chain(error: BaseException) -> list[str]:
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(parts) < 6:
        seen.add(id(current))
        if isinstance(current, ModelHTTPError):
            parts.append(
                f"ModelHTTPError: status_code={current.status_code}, "
                f"cloudflare_code={_cloudflare_error_code(current.body)}"
            )
        elif type(current).__name__ in {
            "WorkflowFailureError",
            "ApplicationError",
            "UsageLimitExceeded",
            "ValueError",
        }:
            parts.append(f"{type(current).__name__}: {str(current)[:300]}")
        else:
            parts.append(type(current).__name__)
        current = current.__cause__ or current.__context__
    return parts


def _cloudflare_error_code(body: object) -> int | None:
    if isinstance(body, dict):
        code = body.get("code")
        if isinstance(code, int):
            return code
        for nested in (body.get("error"), *(body.get("errors") or [])):
            found = _cloudflare_error_code(nested)
            if found is not None:
                return found
    return None


def evaluation_snapshot(
    corpus_version: int,
    model_name: str,
    release_id: UUID,
    daily_neurons: int,
    quota: QuotaStore,
    results: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "corpus_version": corpus_version,
        "model": model_name,
        "prompt_version": PROMPT_VERSION_V3,
        "catalog_release_id": str(release_id),
        "daily_neuron_allowance": daily_neurons,
        "daily_reserved_neurons": quota.daily_reserved_neurons(),
        "results": results,
    }


async def run_case(
    client: Client,
    queue: str,
    engine: Engine,
    case: dict[str, object],
    repetition: int,
    source_reader: TracedSourceReader,
) -> dict[str, object]:
    case_id = str(case["id"])
    actor = IdentityStore(engine).resolve(
        Principal("https://whisky-eval.example/", f"{case_id}-{repetition}-{uuid4()}")
    )
    conditions = ResearchConditions.model_validate(case["input"])
    plan = PlanStore(engine).create(
        actor.id, actor.generation, f"eval {case_id}", conditions
    )
    research = ResearchStore(engine)
    receipt = research.reserve(
        actor.id, actor.generation, plan.id, 1, f"eval-{case_id}-{repetition}"
    )
    starter = TemporalResearchStarter(client, queue, workflow_type="ResearchWorkflowV3")
    started = time.perf_counter()
    run_id = await starter.start(receipt.task_id)
    research.confirm(actor.id, actor.generation, receipt.id, run_id)
    handle = client.get_workflow_handle(receipt.workflow_id)
    questions: list[dict[str, object]] = []
    answered: set[UUID] = set()
    try:
        async with asyncio.timeout(240):
            while True:
                view = research.task(receipt.task_id, actor.id)
                assert view is not None
                if view.status in {"completed", "failed", "cancelled", "superseded"}:
                    break
                if (
                    view.status == "needs_input"
                    and view.question is not None
                    and view.question.id not in answered
                ):
                    question = view.question
                    choices = [
                        {"id": str(choice.id), "name": choice.label}
                        for choice in question.choices
                    ]
                    questions.append({"prompt": question.prompt, "choices": choices})
                    selected = next(
                        (choice for choice in question.choices if "12" in choice.label),
                        question.choices[0],
                    )
                    answer = ClarificationStore(engine).reserve_answer(
                        actor.id,
                        actor.generation,
                        receipt.task_id,
                        question.id,
                        question.waiting_version,
                        1,
                        f"eval-answer-{case_id}-{repetition}-{question.waiting_version}",
                        str(selected.id),
                    )
                    result = await handle.execute_update(
                        "answer", answer, id=str(answer.id), result_type=AnswerResult
                    )
                    if result.acceptance != "accepted":
                        raise RuntimeError(f"Answer rejected: {result.code}")
                    answered.add(question.id)
                await asyncio.sleep(0.2)
    except TimeoutError:
        await handle.cancel()
        status = "timed_out"
        view = research.task(receipt.task_id, actor.id)
    else:
        status = view.status
    report = (
        ReportStore(engine).read(actor.id, view.report_id)
        if view is not None and view.report_id is not None
        else None
    )
    other = IdentityStore(engine).resolve(
        Principal("https://whisky-eval.example/", f"other-{uuid4()}")
    )
    eligible = (
        {
            candidate.item.id: candidate
            for candidate in search_reviewed_candidates(
                engine, report.evaluated_on, conditions.budget_twd
            )
        }
        if report is not None
        else {}
    )
    reviewed_versions = (
        {
            str(candidate.item.bottle.version_id)
            for candidate in search_reviewed_candidates(
                engine, report.evaluated_on, None
            )
        }
        if report is not None
        else set()
    )
    usage = usage_summary(engine, receipt.task_id)
    observations = source_observation_summary(engine, receipt.task_id)
    with engine.connect() as connection:
        observations_valid = all(
            observation["review_status"] == "unreviewed"
            and published_source(
                connection,
                observation["release_id"],
                observation["evidence_id"],
                observation["bottle_version_id"],
            )
            is not None
            and (
                (observation["status"] == "ok")
                == (observation["content_sha256"] is not None)
            )
            and (
                (observation["status"] == "ok")
                == (observation["effective_url"] is not None)
            )
            for observation in observations
        )
    reader_attempts = sum(
        int(attempt["attempts"]) for attempt in usage if attempt["kind"] == "reader"
    )
    gates = {
        "report_persisted": report is not None,
        "owner_isolation": research.task(receipt.task_id, other.id) is None
        and (report is None or ReportStore(engine).read(other.id, report.id) is None),
        "qualified_candidates": report is not None
        and all(
            item.item_id in eligible
            and item.release_id == report.catalog_release_id
            and item.bottle_version_id == eligible[item.item_id].item.bottle.version_id
            and {price.id for price in item.prices}
            == {price.id for price in eligible[item.item_id].prices}
            for item in report.candidates
        ),
        "reviewed_claim_citations": report is not None
        and all(
            item.item_id in eligible
            and bool(claim.sources)
            and (
                any(
                    fact.field == claim.key
                    and fact.value == claim.value
                    and {source.evidence_id for source in claim.sources}
                    <= set(fact.evidence_ids)
                    for fact in eligible[item.item_id].item.facts
                )
                if claim.kind == "fact"
                else any(
                    tag.label == claim.value
                    and {source.evidence_id for source in claim.sources}
                    <= set(tag.evidence_ids)
                    for tag in eligible[item.item_id].item.flavor_tags
                )
            )
            for item in report.candidates
            for claim in item.claims
        ),
        "reviewed_question_choices": report is not None
        and all(
            2 <= len(question["choices"]) <= 5
            and all(choice["id"] in reviewed_versions for choice in question["choices"])
            for question in questions
        ),
        "unreviewed_source_separation": observations_valid
        and len(observations) == (1 if reader_attempts else 0)
        and report is not None
        and {observation.id for observation in report.source_observations}
        == {observation["id"] for observation in observations}
        and all(
            (observation.status == "ok") == (observation.excerpt is not None)
            and observation.review_status == "unreviewed"
            for observation in report.source_observations
        ),
    }
    result: dict[str, object] = {
        "case_id": case_id,
        "repetition": repetition,
        "status": status,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "task_id": str(receipt.task_id),
        "questions": questions,
        "hard_gates": gates,
        "all_hard_gates_passed": all(gates.values()),
        "usage": usage,
        "source_observations": [
            {
                **observation,
                "id": str(observation["id"]),
                "release_id": str(observation["release_id"]),
                "bottle_version_id": str(observation["bottle_version_id"]),
                "evidence_id": str(observation["evidence_id"]),
                "source_checked_on": observation["source_checked_on"].isoformat(),
                "observed_at": observation["observed_at"].isoformat(),
            }
            for observation in observations
        ],
        "source_reads": source_reader.calls.get(receipt.workflow_id, []),
        "error_code": (
            view.error.code if view is not None and view.error is not None else None
        ),
    }
    if report is not None:
        result["model_version"] = report.model_version
        result["prompt_version"] = report.prompt_version
        result["policy_version"] = report.policy_version
        result["summary"] = report.summary
        result["candidate_names"] = [item.name for item in report.candidates]
        result["candidate_details"] = [
            {
                "name": item.name,
                "reason": item.reason,
                "claims": [
                    {
                        "kind": claim.kind,
                        "key": claim.key,
                        "value": claim.value,
                        "evidence_ids": [
                            str(source.evidence_id) for source in claim.sources
                        ],
                    }
                    for claim in item.claims
                ],
                "prices": [
                    {
                        "amount": str(price.amount),
                        "currency": price.currency,
                        "market": price.market,
                        "volume_ml": price.volume_ml,
                        "checked_on": price.checked_on.isoformat()
                        if price.checked_on is not None
                        else None,
                        "evidence_id": str(price.source.evidence_id),
                    }
                    for price in item.prices
                ],
            }
            for item in report.candidates
        ]
        result["unresolved"] = list(report.unresolved)
    if status == "failed":
        try:
            await handle.result()
        except Exception as error:
            result["failure_chain"] = failure_chain(error)
    return result


async def run_all(
    engine: Engine,
    token: str,
    account_id: str,
    daily_neurons: int,
    selected_cases: set[str] | None,
    output_path: Path,
    model_name: str,
) -> dict[str, object]:
    corpus = json.loads(CORPUS.read_text())
    release = load_reviewed_release(
        (ROOT / str(corpus["catalog_manifest"])).read_text()
    )
    CatalogStore(engine).publish(release)
    quota = QuotaStore(engine, daily_neuron_limit=daily_neurons, model_name=model_name)
    source_reader = TracedSourceReader()
    results: list[dict[str, object]] = []
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-live-eval-{uuid4()}"
        async with research_worker(
            client,
            queue,
            engine,
            cloudflare_model(account_id, token, model_name=model_name),
            quota=quota,
            source_reader=source_reader,
        ):
            for case in corpus["cases"]:
                if selected_cases is not None and case["id"] not in selected_cases:
                    continue
                for repetition in range(1, corpus["runs_per_case"] + 1):
                    result = await run_case(
                        client, queue, engine, case, repetition, source_reader
                    )
                    results.append(result)
                    output_path.write_text(
                        json.dumps(
                            evaluation_snapshot(
                                corpus["version"],
                                model_name,
                                release.id,
                                daily_neurons,
                                quota,
                                results,
                            ),
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                    print(
                        f"{result['case_id']} #{repetition}: {result['status']} "
                        f"{result['elapsed_ms']}ms",
                        flush=True,
                    )
    return evaluation_snapshot(
        corpus["version"], model_name, release.id, daily_neurons, quota, results
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append")
    parser.add_argument(
        "--model", choices=tuple(MODEL_NEURON_RATES), default=WORKERS_AI_MODEL
    )
    args = parser.parse_args()
    account_id = os.environ["WHISKY_CLOUDFLARE_ACCOUNT_ID"]
    token = os.environ["WHISKY_CLOUDFLARE_AI_TOKEN"]
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
                token,
                account_id,
                daily_neurons,
                set(args.case) if args.case else None,
                args.output,
                args.model,
            )
        )
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        if any(
            result["status"] != "completed" or not result["all_hard_gates_passed"]
            for result in output["results"]
        ):
            raise SystemExit("Live eval has failed cases or hard gates")
    finally:
        engine.dispose()
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name))
            )


if __name__ == "__main__":
    main()
