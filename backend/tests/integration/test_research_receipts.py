from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from whisky.modules.research.store import ResearchConflict

pytestmark = pytest.mark.integration


def test_reserved_task_is_pending_and_retry_preserves_ids(research_context):
    engine, store, (actor, _), plan = research_context
    receipt = store.reserve(actor.id, actor.generation, plan.id, 1, "start")
    assert receipt is not None, "research receipt must survive before Temporal starts"
    assert receipt.acceptance == "acceptance_pending"
    assert store.reserve(actor.id, actor.generation, plan.id, 1, "start") == receipt
    view = store.task(receipt.task_id, actor.id)
    assert view.status == "acceptance_pending"
    assert view.view_version == 1
    assert view.conditions_revision == 1
    with engine.connect() as connection:
        row = connection.execute(text("SELECT * FROM research_tasks")).one()
        assert row.workflow_id == receipt.workflow_id
        assert row.conditions == plan.conditions.model_dump(mode="json")
        assert row.generation == actor.generation
        assert connection.scalar(text("SELECT count(*) FROM research_commands")) == 1


def test_same_key_different_command_is_rejected(research_context):
    _, store, (actor, _), plan = research_context
    store.reserve(actor.id, actor.generation, plan.id, 1, "same")
    with pytest.raises(ResearchConflict, match="IDEMPOTENCY_CONFLICT"):
        store.reserve(actor.id, actor.generation, plan.id, 2, "same")


def test_new_start_rejects_wrong_owner_and_stale_revision(research_context):
    _, store, (actor, other), plan = research_context
    with pytest.raises(ResearchConflict, match="NOT_FOUND"):
        store.reserve(other.id, other.generation, plan.id, 1, "foreign")
    with pytest.raises(ResearchConflict, match="REVISION_CONFLICT"):
        store.reserve(actor.id, actor.generation, plan.id, 2, "stale")


def test_concurrent_reservations_have_one_task_and_receipt(research_context):
    engine, store, (actor, _), plan = research_context
    barrier = Barrier(2)

    def reserve(_):
        barrier.wait(timeout=10)
        return store.reserve(actor.id, actor.generation, plan.id, 1, "race")

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(reserve, range(2)))
    assert receipts[0] is not None and receipts[0] == receipts[1]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM research_tasks")) == 1
        assert connection.scalar(text("SELECT count(*) FROM research_commands")) == 1


def test_confirmation_queues_once_and_other_owner_cannot_read(research_context):
    _, store, (actor, other), plan = research_context
    receipt = store.reserve(actor.id, actor.generation, plan.id, 1, "start")
    assert receipt is not None
    run_id = str(uuid4())
    confirmed = store.confirm(actor.id, actor.generation, receipt.id, run_id)
    assert confirmed.acceptance == "accepted"
    assert confirmed.task_id == receipt.task_id
    assert store.confirm(actor.id, actor.generation, receipt.id, run_id) == confirmed
    view = store.task(receipt.task_id, actor.id)
    assert view.status == "queued"
    assert view.view_version == 2
    assert store.task(receipt.task_id, other.id) is None
    with pytest.raises(ResearchConflict, match="NOT_FOUND"):
        store.confirm(other.id, other.generation, receipt.id, run_id)


def test_confirmation_never_regresses_worker_progress(research_context):
    engine, store, (actor, _), plan = research_context
    receipt = store.reserve(actor.id, actor.generation, plan.id, 1, "start")
    assert receipt is not None
    with engine.begin() as connection:
        connection.execute(
            text("""
            UPDATE research_tasks SET status = 'researching', view_version = 2
            WHERE id = :id
        """),
            dict(id=receipt.task_id),
        )
    assert (
        store.confirm(actor.id, actor.generation, receipt.id, str(uuid4())).acceptance
        == "accepted"
    )
    view = store.task(receipt.task_id, actor.id)
    assert view.status == "researching" and view.view_version == 2


@pytest.mark.parametrize("change", ["generation = 2", "active = false"])
def test_identity_change_rejects_reserve_confirm_and_private_reads(
    research_context, change
):
    engine, store, (actor, _), plan = research_context
    receipt = store.reserve(actor.id, actor.generation, plan.id, 1, "identity")
    with engine.begin() as connection:
        connection.execute(
            text(f"UPDATE users SET {change} WHERE id = :id"), dict(id=actor.id)
        )
    with pytest.raises(ResearchConflict, match="IDENTITY_CHANGED"):
        store.reserve(actor.id, actor.generation, plan.id, 1, "identity")
    with pytest.raises(ResearchConflict, match="IDENTITY_CHANGED"):
        store.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    assert store.task(receipt.task_id, actor.id) is None


def test_pending_cannot_start_after_revision_changes_but_accepted_replays(
    research_context,
):
    engine, store, (actor, _), plan = research_context
    pending = store.reserve(actor.id, actor.generation, plan.id, 1, "pending")
    accepted = store.reserve(actor.id, actor.generation, plan.id, 1, "accepted")
    accepted = store.confirm(actor.id, actor.generation, accepted.id, str(uuid4()))
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE plans SET conditions_revision = 2 WHERE id = :id"),
            dict(id=plan.id),
        )
    with pytest.raises(ResearchConflict, match="REVISION_CONFLICT"):
        store.reserve(actor.id, actor.generation, plan.id, 1, "pending")
    with pytest.raises(ResearchConflict, match="REVISION_CONFLICT"):
        store.confirm(actor.id, actor.generation, pending.id, str(uuid4()))
    assert store.reserve(actor.id, actor.generation, plan.id, 1, "accepted") == accepted


def test_interruption_rolls_back_receipt_and_task(research_context):
    engine, store, (actor, _), plan = research_context

    def interrupt(connection, _cursor, statement, _parameters, _context, _executemany):
        if "INSERT INTO research_commands" in statement:
            assert connection.scalar(text("SELECT count(*) FROM research_tasks")) == 1
            raise RuntimeError("injected receipt insert interruption")

    event.listen(engine, "before_cursor_execute", interrupt)
    try:
        with pytest.raises(RuntimeError, match="receipt insert interruption"):
            store.reserve(actor.id, actor.generation, plan.id, 1, "rollback")
    finally:
        event.remove(engine, "before_cursor_execute", interrupt)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM research_commands")) == 0
        assert connection.scalar(text("SELECT count(*) FROM research_tasks")) == 0


def test_database_rejects_task_pointing_to_foreign_plan(research_context):
    engine, store, (actor, other), plan = research_context
    receipt = store.reserve(actor.id, actor.generation, plan.id, 1, "owner-fk")
    with pytest.raises(IntegrityError) as error:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE research_tasks SET owner_id = :owner WHERE id = :id"),
                dict(owner=other.id, id=receipt.task_id),
            )
    assert error.value.orig.sqlstate == "23503"


def test_confirmation_rechecks_write_fence_at_the_write(research_context):
    engine, store, (actor, _), plan = research_context
    receipt = store.reserve(actor.id, actor.generation, plan.id, 1, "fence-race")

    def close_fence(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "SELECT c.*, t.workflow_id" in statement:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE research_tasks SET write_allowed = false WHERE id = :id"
                    ),
                    dict(id=receipt.task_id),
                )

    event.listen(engine, "after_cursor_execute", close_fence)
    try:
        with pytest.raises(ResearchConflict, match="TASK_NOT_WRITABLE"):
            store.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    finally:
        event.remove(engine, "after_cursor_execute", close_fence)
    assert store.task(receipt.task_id, actor.id).status == "acceptance_pending"
