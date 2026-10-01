from uuid import uuid4

import pytest
from sqlalchemy import event, text
from test_comparison_reports_v4 import comparison_commit as comparison_commit

from whisky.modules.library.contracts import SaveConclusionV1
from whisky.modules.library.store import LibraryConflict, LibraryStore
from whisky.modules.research.report_store import ReportStore

pytestmark = pytest.mark.integration


@pytest.fixture
def completed_choice(comparison_commit):
    engine, _, actor, commit, comparison = comparison_commit
    saved = ReportStore(engine).save_v4(commit, comparison)
    with engine.connect() as connection:
        plan_id = connection.scalar(
            text("SELECT plan_id FROM research_tasks WHERE id=:task"),
            {"task": saved.task_id},
        )
    report = ReportStore(engine).read(actor.id, saved.id)
    command = SaveConclusionV1(
        key="saved-choice",
        plan_id=plan_id,
        report_id=saved.id,
        expected_conditions_revision=1,
        selected_version_id=report.candidates[0].bottle_version_id,
        reason="想探索這支果香",
        tradeoff="保留當輪取捨",
    )
    return engine, actor, report, command


def test_owned_completed_choice_and_receipt_are_saved_once(completed_choice):
    engine, actor, report, command = completed_choice
    store = LibraryStore(engine)
    saved = store.save_conclusion(actor.id, actor.generation, command)
    assert saved is not None
    assert saved.plan_id == command.plan_id and saved.report_id == report.id
    assert saved.selected_bottle_name == report.candidates[0].name
    assert saved.task_id == report.task_id
    assert saved.conditions_revision == saved.revision == 1
    assert (
        saved.outcome == "selected"
        and saved.selected_version_id == command.selected_version_id
    )
    assert saved.alternative_version_ids == tuple(
        candidate.bottle_version_id for candidate in report.candidates[1:]
    )
    assert store.save_conclusion(actor.id, actor.generation, command) == saved
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM library_conclusions")) == 1
        assert connection.scalar(text("SELECT count(*) FROM library_commands")) == 1


def test_no_suitable_preserves_the_completed_report_alternatives(completed_choice):
    engine, actor, report, command = completed_choice
    saved = LibraryStore(engine).save_conclusion(
        actor.id,
        actor.generation,
        command.model_copy(
            update={"selected_version_id": None, "reason": "沒有適合的"}
        ),
    )
    assert saved is not None and saved.outcome == "no_suitable"
    assert saved.selected_version_id is None
    assert saved.alternative_version_ids == tuple(
        candidate.bottle_version_id for candidate in report.candidates
    )


@pytest.mark.parametrize(
    "mutation", ["foreign", "wrong_plan", "revision", "not_completed", "forged_version"]
)
def test_ineligible_report_cannot_become_a_conclusion(completed_choice, mutation):
    engine, actor, report, command = completed_choice
    owner = actor.id
    expected = "NOT_FOUND"
    if mutation == "foreign":
        from whisky.modules.identity.store import IdentityStore
        from whisky.modules.identity.tokens import Principal

        other = IdentityStore(engine).resolve(
            Principal("https://fixture.example/", "foreign-conclusion")
        )
        owner = other.id
    elif mutation == "wrong_plan":
        command = command.model_copy(update={"plan_id": uuid4()})
    elif mutation == "revision":
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE plans SET conditions_revision=2 WHERE id=:plan"),
                {"plan": command.plan_id},
            )
        expected = "REVISION_CONFLICT"
    elif mutation == "not_completed":
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE research_tasks SET status='researching',report_id=NULL "
                    "WHERE id=:task"
                ),
                {"task": report.task_id},
            )
    else:
        command = command.model_copy(update={"selected_version_id": uuid4()})
        expected = "NOT_A_REPORT_CANDIDATE"
    with pytest.raises(LibraryConflict, match=expected):
        LibraryStore(engine).save_conclusion(owner, actor.generation, command)


def test_changed_payload_with_the_same_key_never_replaces_a_saved_choice(
    completed_choice,
):
    engine, actor, _, command = completed_choice
    store = LibraryStore(engine)
    saved = store.save_conclusion(actor.id, actor.generation, command)
    with pytest.raises(LibraryConflict, match="IDEMPOTENCY_CONFLICT"):
        store.save_conclusion(
            actor.id,
            actor.generation,
            command.model_copy(update={"reason": "改成別的理由"}),
        )
    assert store.save_conclusion(actor.id, actor.generation, command) == saved


def test_a_deleted_plan_cannot_replay_private_conclusion_content(completed_choice):
    engine, actor, _, command = completed_choice
    store = LibraryStore(engine)
    store.save_conclusion(actor.id, actor.generation, command)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE plans SET deleted_at=now() WHERE id=:plan"),
            {"plan": command.plan_id},
        )
    with pytest.raises(LibraryConflict, match="NOT_FOUND"):
        store.save_conclusion(actor.id, actor.generation, command)


def test_a_new_store_reopens_only_its_owned_conclusion_and_historical_conditions(
    completed_choice,
):
    engine, actor, _, command = completed_choice
    store = LibraryStore(engine)
    saved = store.save_conclusion(actor.id, actor.generation, command)
    assert LibraryStore(engine).read_conclusion(actor.id, saved.id) == saved
    assert store.read_conclusion(uuid4(), saved.id) is None
    assert store.read_conclusion(actor.id, uuid4()) is None
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE plans SET conditions_revision=2,"
                "conditions=jsonb_set(conditions,'{budget_twd}','\"900\"') "
                "WHERE id=:plan"
            ),
            {"plan": command.plan_id},
        )
    reopened = LibraryStore(engine).read_conclusion(actor.id, saved.id)
    assert reopened == saved
    assert reopened.conditions_revision == 1


def test_removed_conclusions_cannot_be_read_or_replayed(completed_choice):
    engine, actor, _, command = completed_choice
    store = LibraryStore(engine)
    saved = store.save_conclusion(actor.id, actor.generation, command)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE library_conclusions SET deleted_at=now() WHERE id=:id"),
            {"id": saved.id},
        )
    assert store.read_conclusion(actor.id, saved.id) is None
    with pytest.raises(LibraryConflict, match="NOT_FOUND"):
        store.save_conclusion(actor.id, actor.generation, command)


def test_changed_identity_hides_old_generation_conclusions(completed_choice):
    engine, actor, _, command = completed_choice
    store = LibraryStore(engine)
    saved = store.save_conclusion(actor.id, actor.generation, command)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE users SET generation=generation+1 WHERE id=:owner"),
            {"owner": actor.id},
        )
    assert store.read_conclusion(actor.id, saved.id) is None
    with pytest.raises(LibraryConflict, match="IDENTITY_CHANGED"):
        store.save_conclusion(actor.id, actor.generation, command)


def test_receipt_failure_rolls_back_the_conclusion_and_never_acknowledges_saved(
    completed_choice,
):
    engine, actor, _, command = completed_choice

    def fail_receipt(_, __, statement, ___, ____, _____):
        if "INSERT INTO library_commands" in statement:
            raise RuntimeError("synthetic receipt failure")

    event.listen(engine, "before_cursor_execute", fail_receipt)
    try:
        with pytest.raises(RuntimeError, match="synthetic receipt failure"):
            LibraryStore(engine).save_conclusion(actor.id, actor.generation, command)
    finally:
        event.remove(engine, "before_cursor_execute", fail_receipt)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM library_conclusions")) == 0
        assert connection.scalar(text("SELECT count(*) FROM library_commands")) == 0
    saved = LibraryStore(engine).save_conclusion(actor.id, actor.generation, command)
    assert saved is not None


def test_saved_conclusions_page_without_duplicates_and_keep_their_plan_scope(
    completed_choice,
):
    engine, actor, _, command = completed_choice
    store = LibraryStore(engine)
    saved = [
        store.save_conclusion(
            actor.id,
            actor.generation,
            command.model_copy(
                update={"key": f"choice-{index}", "reason": f"明確選擇 {index}"}
            ),
        )
        for index in range(3)
    ]
    first = store.page_conclusions(actor.id, command.plan_id, limit=2)
    assert len(first.items) == 2 and first.next_cursor is not None
    second = store.page_conclusions(
        actor.id, command.plan_id, limit=2, cursor=first.next_cursor
    )
    assert len(second.items) == 1 and second.next_cursor is None
    assert {item.id for item in (*first.items, *second.items)} == {
        item.id for item in saved
    }
    with pytest.raises(LibraryConflict, match="NOT_FOUND"):
        store.page_conclusions(uuid4(), command.plan_id)
    with pytest.raises(LibraryConflict, match="NOT_FOUND"):
        store.page_conclusions(actor.id, uuid4())
