"""Real DB feedback ownership, revision and receipt behavior."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from test_comparison_reports_v4 import comparison_commit as comparison_commit
from test_library_conclusions import completed_choice as completed_choice

from whisky.modules.library.contracts import SaveBottleFeedbackV1
from whisky.modules.library.store import LibraryConflict, LibraryStore

pytestmark = pytest.mark.integration


@pytest.fixture
def feedback_context(completed_choice):
    engine, actor, _, choice = completed_choice
    return (
        engine,
        actor,
        SaveBottleFeedbackV1(
            key="favorite-once",
            bottle_version_id=choice.selected_version_id,
            expected_revision=0,
            want_to_explore=True,
            tasting="not_tasted",
        ),
    )


def test_bottle_feedback_receipt_replays_without_repeating_creation(feedback_context):
    engine, actor, command = feedback_context
    store = LibraryStore(engine)
    saved = store.save_bottle_feedback(actor.id, actor.generation, command)
    assert saved is not None, "explicit favorites need durable owner-scoped storage"
    assert (
        saved.revision == 1 and saved.want_to_explore and saved.tasting == "not_tasted"
    )
    assert saved.bottle_version_id == command.bottle_version_id
    assert store.save_bottle_feedback(actor.id, actor.generation, command) == saved


def test_new_revision_keeps_favorite_and_disliked_tasting_independent(feedback_context):
    engine, actor, command = feedback_context
    store = LibraryStore(engine)
    first = store.save_bottle_feedback(actor.id, actor.generation, command)
    assert first is not None
    next_command = command.model_copy(
        update={
            "key": "tasting-update",
            "expected_revision": 1,
            "tasting": "disliked",
            "tasting_reason": "不合這次心情",
        }
    )
    changed = store.save_bottle_feedback(actor.id, actor.generation, next_command)
    assert changed is not None and changed.id == first.id and changed.revision == 2
    assert changed.want_to_explore and changed.tasting == "disliked"
    assert (
        store.save_bottle_feedback(actor.id, actor.generation, next_command) == changed
    )
    assert store.save_bottle_feedback(actor.id, actor.generation, command) == first


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("unknown_version", "UNKNOWN_BOTTLE_VERSION"),
        ("revision", "REVISION_CONFLICT"),
        ("identity", "IDENTITY_CHANGED"),
    ],
)
def test_ineligible_feedback_never_becomes_a_successful_write(
    feedback_context, mutation, code
):
    engine, actor, command = feedback_context
    generation = actor.generation
    if mutation == "unknown_version":
        command = command.model_copy(update={"bottle_version_id": uuid4()})
    elif mutation == "revision":
        command = command.model_copy(update={"expected_revision": 1})
    else:
        generation += 1
    with pytest.raises(LibraryConflict, match=code):
        LibraryStore(engine).save_bottle_feedback(actor.id, generation, command)


def test_feedback_reopens_only_for_the_current_owned_generation(feedback_context):
    engine, actor, command = feedback_context
    store = LibraryStore(engine)
    saved = store.save_bottle_feedback(actor.id, actor.generation, command)
    assert store.read_bottle_feedback(actor.id, command.bottle_version_id) == saved
    assert store.read_bottle_feedback(uuid4(), command.bottle_version_id) is None
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE users SET generation=generation+1 WHERE id=:id"),
            {"id": actor.id},
        )
    assert store.read_bottle_feedback(actor.id, command.bottle_version_id) is None
    with pytest.raises(LibraryConflict, match="IDENTITY_CHANGED"):
        store.save_bottle_feedback(actor.id, actor.generation, command)


def test_changed_feedback_payload_cannot_reuse_a_completed_command_key(
    feedback_context,
):
    engine, actor, command = feedback_context
    store = LibraryStore(engine)
    store.save_bottle_feedback(actor.id, actor.generation, command)
    with pytest.raises(LibraryConflict, match="IDEMPOTENCY_CONFLICT"):
        store.save_bottle_feedback(
            actor.id,
            actor.generation,
            command.model_copy(update={"want_to_explore": False}),
        )


def test_concurrent_feedback_updates_accept_only_one_expected_revision(
    feedback_context,
):
    engine, actor, command = feedback_context
    store = LibraryStore(engine)
    store.save_bottle_feedback(actor.id, actor.generation, command)

    def update(tasting):
        try:
            return store.save_bottle_feedback(
                actor.id,
                actor.generation,
                command.model_copy(
                    update={
                        "key": tasting,
                        "expected_revision": 1,
                        "tasting": tasting,
                        "tasting_reason": "明確測試回饋",
                    }
                ),
            )
        except LibraryConflict as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["liked", "disliked"]))
    assert sum(result == "REVISION_CONFLICT" for result in results) == 1
    assert sum(getattr(result, "revision", None) == 2 for result in results) == 1


def test_failed_feedback_receipt_rolls_back_the_actual_write(feedback_context):
    engine, actor, command = feedback_context

    def fail_receipt(_connection, _cursor, statement, _parameters, _context, _many):
        if "INSERT INTO library_commands" in statement and "feedback.save" in statement:
            raise RuntimeError("injected receipt failure")

    event.listen(engine, "before_cursor_execute", fail_receipt)
    try:
        with pytest.raises(RuntimeError, match="injected receipt failure"):
            LibraryStore(engine).save_bottle_feedback(
                actor.id, actor.generation, command
            )
    finally:
        event.remove(engine, "before_cursor_execute", fail_receipt)
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT count(*) FROM library_bottle_feedback")) == 0
        )
        assert connection.scalar(text("SELECT count(*) FROM library_commands")) == 0


def test_feedback_pagination_is_owner_scoped_and_has_no_missing_tied_rows(
    completed_choice,
):
    engine, actor, report, _ = completed_choice
    store = LibraryStore(engine)
    saved = [
        store.save_bottle_feedback(
            actor.id,
            actor.generation,
            SaveBottleFeedbackV1(
                key=str(candidate.bottle_version_id),
                bottle_version_id=candidate.bottle_version_id,
                expected_revision=0,
                want_to_explore=True,
                tasting="not_tasted",
            ),
        )
        for candidate in report.candidates
    ]
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE library_bottle_feedback SET updated_at='2026-10-01T00:00:00Z'")
        )
    first = store.page_bottle_feedback(actor.id, 2)
    assert len(first.items) == 2, (
        "favorites and tasting must be recoverable in bounded own pages"
    )
    assert first.next_cursor is not None
    second = store.page_bottle_feedback(actor.id, 2, first.next_cursor)
    assert second.next_cursor is None
    assert {item.id for item in (*first.items, *second.items)} == {
        item.id for item in saved
    }
    assert not store.page_bottle_feedback(uuid4()).items
