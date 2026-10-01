from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event, current_thread
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text

from whisky.modules.catalog.publication import load_reviewed_release
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.store import IdentityStore
from whisky.modules.identity.tokens import Principal
from whisky.modules.research.activities import ResearchActivities
from whisky.modules.research.comparison_v4 import comparison_artifact_v4
from whisky.modules.research.contracts import ReportCommit
from whisky.modules.research.inputs_v4 import (
    ResearchInputV4,
    StartCommandV4,
    StartTurnV4,
)
from whisky.modules.research.report import ReportCandidate, ReportDraft
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.run_store import ResearchRunStore
from whisky.modules.research.selection_v4 import select_research
from whisky.modules.research.store import ResearchConflict, ResearchStore

pytestmark = pytest.mark.integration


def test_migration_from_production_schema_preserves_a_legacy_report(postgres_url):
    engine = create_engine(postgres_url)
    try:
        config = Config()
        config.set_main_option(
            "script_location", str(Path(__file__).parents[2] / "migrations")
        )
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0012_recovery_gate")
            version = connection.scalar(text("SELECT version_num FROM alembic_version"))
            reports = connection.scalar(text("SELECT count(*) FROM research_reports"))
            tasks = connection.scalar(text("SELECT count(*) FROM research_tasks"))
            print(f"local baseline: schema={version}, reports={reports}, tasks={tasks}")
            assert version == "0012_recovery_gate"
            assert (reports, tasks) == (0, 0)
        actor = IdentityStore(engine).resolve(
            Principal("https://migration-fixture.example/", "legacy")
        )
        plan = PlanStore(engine).create(
            actor.id,
            actor.generation,
            "legacy",
            ResearchConditions(entry="beginner", goal="舊版報告"),
        )
        receipt = ResearchStore(engine).reserve(
            actor.id, actor.generation, plan.id, 1, "legacy"
        )
        reports = ReportStore(engine)
        # Seed the predecessor wire shape; current code requires newer columns.
        report_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO research_reports
                    (id,task_id,owner_id,generation,conditions_revision,artifact_key,
                     evaluated_on,policy_version,prompt_version,model_version,
                     schema_version,content)
                VALUES (:id,:task,:owner,:generation,1,'legacy-artifact',CURRENT_DATE,
                        'price-30d-v1','legacy-v3','legacy-fixture',1,
                        '{"summary": "合成舊版空報告", "unresolved": []}'::jsonb)
            """),
                dict(
                    id=report_id,
                    task=receipt.task_id,
                    owner=actor.id,
                    generation=actor.generation,
                ),
            )
            connection.execute(
                text("""
                UPDATE research_tasks SET status='completed',report_id=:report
                WHERE id=:task
            """),
                dict(report=report_id, task=receipt.task_id),
            )
        original = reports.read(actor.id, report_id)
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            assert connection.scalar(text("SELECT count(*) FROM research_reports")) == 1
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM research_report_comparisons")
                )
                == 0
            )
        assert reports.read(actor.id, report_id) == original
        assert reports.read_comparison_v4(actor.id, report_id) is None
    finally:
        engine.dispose()


@pytest.fixture
def comparison_commit(research_context):
    engine, research, (actor, _), plan = research_context
    manifest = Path(__file__).parents[3] / "data/catalog/first-journey.reviewed.json"
    CatalogStore(engine).publish(load_reviewed_release(manifest.read_text()))
    captured = ResearchInputV4()
    receipt = research.reserve_turn_v4(
        actor.id,
        actor.generation,
        StartTurnV4(
            uuid4(),
            uuid4(),
            StartCommandV4(
                type="start_v4",
                key="comparison",
                plan_id=plan.id,
                conditions_revision=1,
                input=captured,
            ),
        ),
    )
    context = ResearchRunStore(engine).begin_v4(receipt.task_id, "test-v4").context
    snapshot = ResearchActivities(engine)._catalog_snapshot(context)
    selection = select_research(
        context.conditions, snapshot, None, intent=captured.intent
    )
    comparison = comparison_artifact_v4(
        context.conditions, snapshot, None, captured.intent, selection
    )
    items = {item.index: item for item in snapshot.items}
    draft = ReportDraft(
        "已覆核風格選擇",
        tuple(
            ReportCandidate(
                items[index].release_id,
                items[index].item_id,
                items[index].claims,
                "只引用已覆核描述",
                items[index].price_ids,
            )
            for index in selection.candidate_indices
        ),
    )
    commit = ReportCommit(
        receipt.task_id,
        actor.id,
        actor.generation,
        "final-v4",
        draft,
        context.policy_version,
        context.prompt_version,
        "fixture-v4",
    )
    return engine, research, actor, commit, comparison


def test_v4_report_and_comparison_are_one_immutable_artifact(comparison_commit):
    engine, research, actor, commit, comparison = comparison_commit
    saved = ReportStore(engine).save_v4(commit, comparison)
    assert research.task(commit.task_id, actor.id).report_id == saved.id
    with engine.connect() as connection:
        stored = connection.scalar(
            text("SELECT content FROM research_report_comparisons WHERE report_id=:id"),
            {"id": saved.id},
        )
        assert stored["schema_version"] == 4
        assert len(stored["candidates"]) == len(commit.draft.candidates)
    replayed = ReportStore(engine).save_v4(
        replace(commit, draft=replace(commit.draft, summary="重送不改寫")), comparison
    )
    assert replayed == saved
    assert ReportStore(engine).read(actor.id, saved.id).summary == commit.draft.summary


def test_fabricated_comparison_rolls_back_report_and_task(comparison_commit):
    engine, research, actor, commit, comparison = comparison_commit
    before = research.task(commit.task_id, actor.id)
    forged = replace(
        comparison,
        candidates=(
            replace(comparison.candidates[0], common_tags=("捏造的共同風味",)),
            *comparison.candidates[1:],
        ),
    )
    with pytest.raises(ValueError, match="COMPARISON_MISMATCH"):
        ReportStore(engine).save_v4(commit, forged)
    after = research.task(commit.task_id, actor.id)
    assert (after.status, after.view_version, after.report_id) == (
        before.status,
        before.view_version,
        None,
    )
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM research_reports")) == 0


def test_comparison_read_keeps_snapshot_and_scoped_sources(comparison_commit):
    engine, _, actor, commit, comparison = comparison_commit
    reports = ReportStore(engine)
    saved = reports.save_v4(commit, comparison)
    view = reports.read_comparison_v4(actor.id, saved.id)
    assert view.report_id == saved.id
    assert view.conditions_revision == 1
    assert view.comparison == comparison
    assert {item.reference for item in view.items} == {
        candidate.candidate for candidate in comparison.candidates
    }
    assert all(item.name and item.sources for item in view.items)
    assert all(
        source.url.startswith("https://")
        for item in view.items
        for source in item.sources
    )
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE plans SET conditions_revision=2 WHERE owner_id=:owner"),
            {"owner": actor.id},
        )
    historical = reports.read_comparison_v4(actor.id, saved.id)
    assert historical == view


def test_comparison_read_hides_foreign_missing_and_changed_generation(
    comparison_commit,
):
    engine, _, actor, commit, comparison = comparison_commit
    reports = ReportStore(engine)
    saved = reports.save_v4(commit, comparison)
    assert reports.read_comparison_v4(uuid4(), saved.id) is None
    assert reports.read_comparison_v4(actor.id, uuid4()) is None
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE users SET generation=generation+1 WHERE id=:owner"),
            {"owner": actor.id},
        )
    assert reports.read_comparison_v4(actor.id, saved.id) is None


def test_v4_cannot_adopt_a_legacy_report_committed_before_its_lock(comparison_commit):
    engine, _, actor, commit, comparison = comparison_commit
    reports = ReportStore(engine)
    reached = Event()
    proceed = Event()

    def pause_v4_before_actor_lock(_, __, statement, ___, ____, _____):
        if (
            current_thread().name.startswith("comparison-race")
            and "FROM users" in statement
            and "FOR UPDATE" in statement
            and not reached.is_set()
        ):
            reached.set()
            assert proceed.wait(10)

    event.listen(engine, "before_cursor_execute", pause_v4_before_actor_lock)
    try:
        with ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="comparison-race"
        ) as pool:
            future = pool.submit(reports.save_v4, commit, comparison)
            try:
                assert reached.wait(10)
                saved = reports.save(
                    actor.id,
                    actor.generation,
                    commit.task_id,
                    commit.artifact_key,
                    replace(commit.draft, summary="合成並行舊版報告"),
                    policy_version=commit.policy_version,
                    prompt_version=commit.prompt_version,
                    model_version=commit.model_version,
                )
            finally:
                proceed.set()
            with pytest.raises(ResearchConflict, match="COMPARISON_MISSING"):
                future.result(timeout=10)
        assert reports.read(actor.id, saved.id).summary == "合成並行舊版報告"
        assert reports.read_comparison_v4(actor.id, saved.id) is None
    finally:
        proceed.set()
        event.remove(engine, "before_cursor_execute", pause_v4_before_actor_lock)
