"""Restoring a product DB cannot reopen data revoked outside its PITR point."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_control_recovery import PagedJournal

from whisky.modules.control.journal import (
    intent_record,
    result_record,
    write_verified,
)
from whisky.modules.control.recovery import RecoveryError, reconcile_control_log
from whisky.modules.control.store import ControlStore
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore

pytestmark = pytest.mark.integration


def _recorded_delete(engine, actor, plan, journal):
    store = ControlStore(engine)
    command = store.reserve(
        actor.id, actor.generation, "plan.delete", plan.id, str(uuid4())
    )
    write_verified(journal, *intent_record(command))
    store.confirm_intent(command.id)
    applied = store.apply(command.id)
    write_verified(journal, *result_record(applied))
    store.confirm_result(command.id)
    return command


def _restore_before_delete(engine, command):
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE plans SET deleted_at=NULL WHERE id=:plan"),
            {"plan": command.target_id},
        )
        connection.execute(
            text("DELETE FROM control_commands WHERE id=:id"), {"id": command.id}
        )


def test_completed_plan_delete_reapplies_after_pitr_and_is_idempotent(research_context):
    engine, _, (actor, _), plan = research_context
    journal = PagedJournal(page_size=1)
    command = _recorded_delete(engine, actor, plan, journal)
    _restore_before_delete(engine, command)
    assert PlanStore(engine).read(plan.id, actor.id) is not None

    restored = reconcile_control_log(journal, ControlStore(engine))
    assert restored[0].id == command.id
    assert restored[0].status == "completed"
    assert PlanStore(engine).read(plan.id, actor.id) is None
    assert ControlStore(engine).read(command.id, actor.id).status == "completed"
    assert reconcile_control_log(journal, ControlStore(engine)) == restored


def test_database_receipt_rejects_a_whole_missing_external_pair(research_context):
    engine, _, (actor, _), plan = research_context
    journal = PagedJournal()
    command = _recorded_delete(engine, actor, plan, journal)
    journal.objects.clear()

    with pytest.raises(RecoveryError, match="missing outside"):
        reconcile_control_log(journal, ControlStore(engine))
    assert ControlStore(engine).read(command.id, actor.id).status == "completed"


def test_failed_later_page_does_not_apply_an_earlier_delete(research_context):
    engine, _, (actor, _), plan = research_context
    journal = PagedJournal(page_size=1)
    command = _recorded_delete(engine, actor, plan, journal)
    _restore_before_delete(engine, command)
    journal.fail_on_page = journal.page_calls + 2

    with pytest.raises(RecoveryError, match="list"):
        reconcile_control_log(journal, ControlStore(engine))
    assert PlanStore(engine).read(plan.id, actor.id) is not None
    assert ControlStore(engine).read(command.id, actor.id) is None


def test_old_pending_intent_rechecks_and_writes_result(research_context):
    engine, _, (actor, _), plan = research_context
    journal = PagedJournal(page_size=1)
    store = ControlStore(engine)
    command = store.reserve(
        actor.id, actor.generation, "plan.delete", plan.id, str(uuid4())
    )
    old = replace(command, created_at=datetime.now(UTC) - timedelta(days=45))
    write_verified(journal, *intent_record(old))
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM control_commands WHERE id=:id"), {"id": command.id}
        )

    restored = reconcile_control_log(journal, store)
    assert restored[0].status == "completed"
    assert PlanStore(engine).read(plan.id, actor.id) is None
    assert len(journal.objects) == 2
    assert reconcile_control_log(journal, store) == restored


def test_external_rejection_does_not_delete_plan(research_context):
    engine, _, (actor, _), plan = research_context
    journal = PagedJournal(page_size=1)
    store = ControlStore(engine)
    command = store.reserve(
        actor.id, actor.generation, "plan.delete", plan.id, str(uuid4())
    )
    write_verified(journal, *intent_record(command))
    rejected = replace(
        command,
        status="effect_rejected",
        result={
            "outcome": "rejected",
            "code": "REVISION_CONFLICT",
            "effectAt": datetime.now(UTC).isoformat(),
        },
    )
    write_verified(journal, *result_record(rejected))
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM control_commands WHERE id=:id"), {"id": command.id}
        )

    restored = reconcile_control_log(journal, store)
    assert restored[0].status == "rejected"
    assert PlanStore(engine).read(plan.id, actor.id) is not None
    assert store.read(command.id, actor.id).status == "rejected"


def test_completed_receipt_with_visible_plan_fails_closed(research_context):
    engine, _, (actor, _), plan = research_context
    journal = PagedJournal(page_size=1)
    command = _recorded_delete(engine, actor, plan, journal)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE plans SET deleted_at=NULL WHERE id=:id"),
            {"id": plan.id},
        )

    with pytest.raises(RecoveryError, match="effect"):
        reconcile_control_log(journal, ControlStore(engine))
    assert ControlStore(engine).read(command.id, actor.id).status == "completed"
    assert PlanStore(engine).read(plan.id, actor.id) is not None


def test_old_generation_command_does_not_touch_new_plan(research_context):
    engine, _, (actor, _), old_plan = research_context
    journal = PagedJournal(page_size=1)
    command = _recorded_delete(engine, actor, old_plan, journal)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM control_commands WHERE id=:id"), {"id": command.id}
        )
        connection.execute(
            text("UPDATE users SET generation=2,active=true WHERE id=:id"),
            {"id": actor.id},
        )
    new_plan = PlanStore(engine).create(
        actor.id,
        2,
        "new-generation-plan",
        ResearchConditions(entry="beginner", goal="新的探索"),
    )

    assert reconcile_control_log(journal, ControlStore(engine))[0].id == command.id
    assert PlanStore(engine).read(new_plan.id, actor.id) is not None
    assert PlanStore(engine).read(old_plan.id, actor.id) is None


def test_unreadable_object_fails_before_effect(research_context):
    engine, _, (actor, _), plan = research_context
    journal = PagedJournal(page_size=1)
    command = _recorded_delete(engine, actor, plan, journal)
    _restore_before_delete(engine, command)
    journal.fail_read = True

    with pytest.raises(RecoveryError, match="read"):
        reconcile_control_log(journal, ControlStore(engine))
    assert PlanStore(engine).read(plan.id, actor.id) is not None


def test_completed_result_matches_effect_applied_receipt(research_context):
    engine, _, (actor, _), plan = research_context
    journal = PagedJournal(page_size=1)
    store = ControlStore(engine)
    command = _recorded_delete(engine, actor, plan, journal)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE control_commands SET status='effect_applied' WHERE id=:id"),
            {"id": command.id},
        )

    restored = reconcile_control_log(journal, store)
    assert restored[0].status == "completed"
    assert store.read(command.id, actor.id).result == restored[0].result


def test_mismatched_outside_result_cannot_overwrite_applied_receipt(research_context):
    engine, _, (actor, _), plan = research_context
    journal = PagedJournal(page_size=1)
    store = ControlStore(engine)
    command = _recorded_delete(engine, actor, plan, journal)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE control_commands SET status='effect_applied' WHERE id=:id"),
            {"id": command.id},
        )
    result_key, result_body = result_record(store.read(command.id, actor.id))
    altered = json.loads(result_body)
    altered["effectAt"] = datetime.now(UTC).isoformat()
    journal.objects[result_key] = json.dumps(altered).encode()

    with pytest.raises(RecoveryError, match="result"):
        reconcile_control_log(journal, store)
    assert store.read(command.id, actor.id).status == "effect_applied"


def test_completed_delete_with_tombstone_and_missing_receipt_restores(research_context):
    engine, _, (actor, _), plan = research_context
    journal = PagedJournal(page_size=1)
    command = _recorded_delete(engine, actor, plan, journal)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM control_commands WHERE id=:id"), {"id": command.id}
        )

    restored = reconcile_control_log(journal, ControlStore(engine))
    assert restored[0].status == "completed"
    assert PlanStore(engine).read(plan.id, actor.id) is None


def test_completed_actor_delete_with_missing_receipt_keeps_actor_disabled(
    research_context,
):
    engine, _, (actor, _), plan = research_context
    journal = PagedJournal(page_size=1)
    store = ControlStore(engine)
    command = store.reserve(
        actor.id, actor.generation, "actor.delete", actor.id, str(uuid4())
    )
    write_verified(journal, *intent_record(command))
    store.confirm_intent(command.id)
    applied = store.apply(command.id)
    write_verified(journal, *result_record(applied))
    store.confirm_result(command.id)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM control_commands WHERE id=:id"), {"id": command.id}
        )

    restored = reconcile_control_log(journal, store)
    assert restored[0].status == "completed"
    assert PlanStore(engine).read(plan.id, actor.id) is None
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT active FROM users WHERE id=:id"), {"id": actor.id}
            )
            is False
        )


def test_old_generation_applied_effect_without_external_result_is_finished(
    research_context,
):
    engine, _, (actor, _), old_plan = research_context
    journal = PagedJournal(page_size=1)
    store = ControlStore(engine)
    command = store.reserve(
        actor.id, actor.generation, "plan.delete", old_plan.id, str(uuid4())
    )
    write_verified(journal, *intent_record(command))
    store.confirm_intent(command.id)
    applied = store.apply(command.id)
    assert applied.status == "effect_applied"
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE users SET generation=2,active=true WHERE id=:id"),
            {"id": actor.id},
        )
    new_plan = PlanStore(engine).create(
        actor.id,
        2,
        "new-generation-plan",
        ResearchConditions(entry="beginner", goal="新的探索"),
    )

    restored = reconcile_control_log(journal, store)
    assert restored[0].status == "completed"
    assert len(journal.objects) == 2
    assert PlanStore(engine).read(new_plan.id, actor.id) is not None


def test_completed_condition_changes_replay_by_revision_despite_clock_skew(
    research_context,
):
    engine, _, (actor, _), plan = research_context
    journal = PagedJournal(page_size=1)
    store = ControlStore(engine)
    first = ResearchConditions(entry="beginner", goal="先找果香")
    second = ResearchConditions(entry="beginner", goal="再找泥煤")
    for revision, conditions in ((1, first), (2, second)):
        command = store.reserve(
            actor.id,
            actor.generation,
            "plan.change_conditions",
            plan.id,
            str(uuid4()),
            expected_revision=revision,
            conditions=conditions,
        )
        write_verified(journal, *intent_record(command))
        store.confirm_intent(command.id)
        applied = store.apply(command.id)
        assert applied.status == "effect_applied"
        # A remote clock can run backwards even though the DB revisions cannot.
        effect_at = datetime(2026, 9, 29, 12, 0, 3 - revision, tzinfo=UTC)
        skewed = replace(
            applied,
            result={"outcome": "completed", "effectAt": effect_at.isoformat()},
        )
        with engine.begin() as connection:
            connection.execute(
                text("""
                UPDATE control_commands SET result=CAST(:result AS jsonb)
                WHERE id=:id
                """),
                dict(result=json.dumps(skewed.result), id=command.id),
            )
        write_verified(journal, *result_record(skewed))
        store.confirm_result(command.id)

    with engine.begin() as connection:
        connection.execute(
            text("""
            UPDATE plans SET conditions_revision=1,
                conditions=CAST(:conditions AS jsonb) WHERE id=:id
            """),
            dict(id=plan.id, conditions=plan.conditions.canonical_json()),
        )
        connection.execute(
            text("DELETE FROM control_commands WHERE target_id=:plan"),
            {"plan": plan.id},
        )

    restored = reconcile_control_log(journal, store)
    assert [item.expected_revision for item in restored] == [1, 2]
    current = PlanStore(engine).read(plan.id, actor.id)
    assert current is not None
    assert current.conditions_revision == 3
    assert current.conditions == second
