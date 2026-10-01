"""Deletion removes library originals, not merely their visible projection."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_account_export_store import populate
from test_comparison_reports_v4 import comparison_commit as comparison_commit
from test_control_recovery import PagedJournal
from test_library_conclusions import completed_choice as completed_choice

import whisky.modules.control.store as control_module
from whisky.modules.control.journal import intent_record, result_record, write_verified
from whisky.modules.control.recovery import RecoveryError, reconcile_control_log
from whisky.modules.control.store import ControlStore
from whisky.modules.identity.store import IdentityStore
from whisky.modules.identity.tokens import Principal
from whisky.modules.library.contracts import SaveLongTermPreferencesV1
from whisky.modules.library.preference_store import PreferenceStore
from whisky.modules.library.public import purge_actor_library, purge_plan_library

pytestmark = pytest.mark.integration


TABLES = (
    "library_conclusions",
    "library_commands",
    "library_bottle_feedback",
    "library_preferences",
)


def delete(engine, actor, choice, kind, journal=None):
    controls = ControlStore(engine)
    command = controls.reserve(
        actor.id,
        actor.generation,
        kind,
        actor.id if kind == "actor.delete" else choice.plan_id,
        str(uuid4()),
    )
    if journal is not None:
        write_verified(journal, *intent_record(command))
    controls.confirm_intent(command.id)
    applied = controls.apply(command.id)
    assert applied.status == "effect_applied"
    if journal is not None:
        write_verified(journal, *result_record(applied))
        controls.confirm_result(command.id)
    return controls, command


def count(connection, table, owner):
    return connection.scalar(
        text(f"SELECT count(*) FROM {table} WHERE owner_id=:owner"),
        dict(owner=owner),
    )


def snapshot_library(engine, owner):
    with engine.connect() as connection:
        return {
            table: list(
                connection.execute(
                    text(
                        f"SELECT to_jsonb(row) FROM {table} row WHERE owner_id=:owner"
                    ),
                    dict(owner=owner),
                ).scalars()
            )
            for table in TABLES
        }


def restore_library(connection, originals):
    for table, rows in originals.items():
        connection.execute(
            text(
                f"INSERT INTO {table} SELECT * FROM "
                f"jsonb_populate_recordset(NULL::{table},CAST(:rows AS jsonb)) "
                "ON CONFLICT DO NOTHING"
            ),
            dict(rows=json.dumps(rows)),
        )


def test_plan_delete_erases_conclusion_and_receipt_but_keeps_independent_feedback(
    completed_choice,
):
    engine, actor, _ = populate(completed_choice)
    _, _, _, choice = completed_choice
    delete(engine, actor, choice, "plan.delete")
    with engine.connect() as connection:
        assert count(connection, "library_conclusions", actor.id) == 0
        assert (
            connection.scalar(
                text("""
                SELECT count(*) FROM library_commands
                WHERE owner_id=:owner AND scope='conclusions.save'
            """),
                dict(owner=actor.id),
            )
            == 0
        )
        assert count(connection, "library_bottle_feedback", actor.id) == 1
        assert count(connection, "library_preferences", actor.id) == 1


def test_actor_delete_erases_all_library_originals_and_retained_responses(
    completed_choice,
):
    engine, actor, _ = populate(completed_choice)
    _, _, _, choice = completed_choice
    delete(engine, actor, choice, "actor.delete")
    with engine.connect() as connection:
        for table in TABLES:
            assert count(connection, table, actor.id) == 0


def test_receipt_plan_scope_survives_missing_conclusion_and_changed_wire_json(
    completed_choice,
):
    engine, actor, _ = populate(completed_choice)
    _, _, _, choice = completed_choice
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM library_conclusions WHERE owner_id=:owner"),
            dict(owner=actor.id),
        )
        connection.execute(
            text("""
                UPDATE library_commands
                SET response=jsonb_set(
                    response,'{planId}',to_jsonb(CAST(:other AS text))
                )
                WHERE owner_id=:owner AND scope='conclusions.save'
            """),
            dict(owner=actor.id, other=uuid4()),
        )
    delete(engine, actor, choice, "plan.delete")
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("""
                SELECT count(*) FROM library_commands
                WHERE owner_id=:owner AND scope='conclusions.save'
            """),
                dict(owner=actor.id),
            )
            == 0
        )


@pytest.mark.parametrize("kind", ["plan.delete", "actor.delete"])
def test_deletion_fences_completed_tasks_without_destroying_historical_report(
    completed_choice, kind
):
    engine, actor, _ = populate(completed_choice)
    _, _, report, choice = completed_choice
    delete(engine, actor, choice, kind)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status,write_allowed FROM research_tasks WHERE id=:task"),
            dict(task=report.task_id),
        ).one()
        assert row.status == "completed"
        assert row.write_allowed is False
        assert (
            connection.scalar(
                text("SELECT count(*) FROM research_reports WHERE id=:report"),
                dict(report=report.id),
            )
            == 1
        )


@pytest.mark.parametrize("kind", ["plan.delete", "actor.delete"])
@pytest.mark.parametrize("legacy_write_flag", [False, True], ids=["current", "legacy"])
def test_restore_cleans_library_originals_even_when_delete_fence_survives(
    completed_choice, kind, legacy_write_flag
):
    engine, actor, _ = populate(completed_choice)
    _, _, report, choice = completed_choice
    originals = snapshot_library(engine, actor.id)
    journal = PagedJournal()
    controls, _ = delete(engine, actor, choice, kind, journal)
    with engine.begin() as connection:
        restore_library(connection, originals)
        if legacy_write_flag:
            connection.execute(
                text("UPDATE research_tasks SET write_allowed=true WHERE id=:task"),
                dict(task=report.task_id),
            )
    reconcile_control_log(journal, controls)
    with engine.connect() as connection:
        assert count(connection, "library_conclusions", actor.id) == 0
        if kind == "actor.delete":
            for table in TABLES:
                assert count(connection, table, actor.id) == 0


def test_library_cleanup_failure_rolls_back_the_entire_actor_effect(
    completed_choice, monkeypatch
):
    engine, actor, _ = populate(completed_choice)
    _, _, _, choice = completed_choice
    original = control_module.purge_actor_library

    def fail_after_cleanup(connection, owner, generation):
        original(connection, owner, generation)
        raise RuntimeError("injected cleanup failure")

    monkeypatch.setattr(control_module, "purge_actor_library", fail_after_cleanup)
    with pytest.raises(RuntimeError, match="injected cleanup failure"):
        delete(engine, actor, choice, "actor.delete")
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT active,generation FROM users WHERE id=:owner"),
            dict(owner=actor.id),
        ).one()
        assert row.active is True and row.generation == actor.generation
        for table in TABLES:
            assert count(connection, table, actor.id) > 0
        assert (
            connection.scalar(
                text("SELECT status FROM control_commands WHERE kind='actor.delete'")
            )
            == "intent_confirmed"
        )


def test_actor_cleanup_keeps_another_accounts_preference_and_receipt(completed_choice):
    engine, actor, _ = populate(completed_choice)
    _, _, _, choice = completed_choice
    foreign = IdentityStore(engine).resolve(
        Principal("https://purge-fixture.example/", "foreign")
    )
    PreferenceStore(engine).save(
        foreign.id,
        foreign.generation,
        SaveLongTermPreferencesV1(key="foreign", expected_revision=0, preferences=()),
    )
    delete(engine, actor, choice, "actor.delete")
    with engine.connect() as connection:
        assert count(connection, "library_preferences", foreign.id) == 1
        assert count(connection, "library_commands", foreign.id) == 1


@pytest.mark.parametrize("kind", ["actor", "plan"])
def test_cleanup_rejects_a_live_scope_without_erasing_its_originals(
    completed_choice, kind
):
    engine, actor, _ = populate(completed_choice)
    _, _, _, choice = completed_choice
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="fence"):
            if kind == "actor":
                purge_actor_library(connection, actor.id, actor.generation)
            else:
                purge_plan_library(
                    connection, actor.id, actor.generation, choice.plan_id
                )
        for table in TABLES:
            assert count(connection, table, actor.id) > 0


def test_synthetic_future_generation_survives_an_old_actor_delete_reconciliation(
    completed_choice,
):
    engine, actor, _ = populate(completed_choice)
    _, _, _, choice = completed_choice
    originals = snapshot_library(engine, actor.id)
    journal = PagedJournal()
    controls, _ = delete(engine, actor, choice, "actor.delete", journal)
    future = actor.generation + 2
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE users SET active=true,generation=:future WHERE id=:owner"),
            dict(owner=actor.id, future=future),
        )
        restore_library(connection, originals)
    saved = PreferenceStore(engine).save(
        actor.id,
        future,
        SaveLongTermPreferencesV1(key="future", expected_revision=0, preferences=()),
    )
    reconcile_control_log(journal, controls)
    assert PreferenceStore(engine).read(actor.id) == saved
    with engine.connect() as connection:
        for table in TABLES:
            assert (
                connection.scalar(
                    text(
                        f"SELECT count(*) FROM {table} "
                        "WHERE owner_id=:owner AND generation<=:old"
                    ),
                    dict(owner=actor.id, old=actor.generation),
                )
                == 0
            )


def test_later_recovery_rejection_rolls_back_cleanup_and_child_refencing(
    completed_choice,
):
    engine, actor, _ = populate(completed_choice)
    _, _, report, choice = completed_choice
    originals = snapshot_library(engine, actor.id)
    journal = PagedJournal()
    controls, command = delete(engine, actor, choice, "plan.delete", journal)
    with engine.begin() as connection:
        restore_library(connection, originals)
        connection.execute(
            text("UPDATE research_tasks SET write_allowed=true WHERE id=:task"),
            dict(task=report.task_id),
        )
        connection.execute(
            text("""
                UPDATE control_commands SET result=jsonb_set(
                    result,'{effectAt}',to_jsonb(CAST(:stamp AS text))
                ) WHERE id=:command
            """),
            dict(command=command.id, stamp="2000-01-01T00:00:00+00:00"),
        )
    with pytest.raises(RecoveryError, match="outside result disagree"):
        reconcile_control_log(journal, controls)
    with engine.connect() as connection:
        for table in TABLES:
            assert count(connection, table, actor.id) > 0
        assert (
            connection.scalar(
                text("SELECT write_allowed FROM research_tasks WHERE id=:task"),
                dict(task=report.task_id),
            )
            is True
        )
