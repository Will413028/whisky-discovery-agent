"""Plan deletion erases originals while retaining safe command deduplication."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from test_control_recovery import PagedJournal
from test_plans import conditions
from test_plans import plan_context as plan_context

import whisky.modules.control.store as control_module
from whisky.modules.control.journal import intent_record, result_record, write_verified
from whisky.modules.control.recovery import reconcile_control_log
from whisky.modules.control.store import ControlStore
from whisky.modules.discovery.public import (
    purge_actor_plan_originals,
    purge_plan_originals,
)
from whisky.modules.discovery.store import PlanConflict

pytestmark = pytest.mark.integration


def remove(engine, actor, plan, kind="plan.delete", journal=None):
    store = ControlStore(engine)
    command = store.reserve(
        actor.id,
        actor.generation,
        kind,
        actor.id if kind == "actor.delete" else plan.id,
        str(uuid4()),
    )
    if journal is not None:
        write_verified(journal, *intent_record(command))
    store.confirm_intent(command.id)
    applied = store.apply(command.id)
    assert applied.status == "effect_applied"
    if journal is not None:
        write_verified(journal, *result_record(applied))
        store.confirm_result(command.id)
    return store


@pytest.mark.parametrize("kind", ["plan.delete", "actor.delete"])
def test_deleted_plan_and_creation_receipt_contain_no_condition_originals(
    plan_context, kind
):
    engine, store, (actor, other) = plan_context
    plan = store.create(actor.id, actor.generation, "private", conditions())
    untouched = store.create(other.id, other.generation, "private", conditions())
    remove(engine, actor, plan, kind)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT conditions FROM plans WHERE id=:id"), dict(id=plan.id)
            )
            == {}
        )
        receipt = connection.execute(
            text("SELECT result FROM discovery_commands WHERE target_id=:id"),
            dict(id=plan.id),
        ).scalar_one()
        assert receipt == {"generation": actor.generation, "conditions_revision": 1}
    assert store.read(untouched.id, other.id) == untouched


def test_replaying_create_for_deleted_plan_rejects_instead_of_returning_original(
    plan_context,
):
    engine, store, (actor, _) = plan_context
    plan = store.create(actor.id, actor.generation, "private", conditions())
    remove(engine, actor, plan)
    with pytest.raises(PlanConflict, match="NOT_FOUND"):
        store.create(actor.id, actor.generation, "private", conditions())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM plans")) == 1
        assert connection.scalar(text("SELECT count(*) FROM discovery_commands")) == 1


@pytest.mark.parametrize("kind", ["plan.delete", "actor.delete"])
def test_restore_cleans_plan_originals_beneath_surviving_delete_fence(
    plan_context, kind
):
    engine, store, (actor, _) = plan_context
    plan = store.create(actor.id, actor.generation, "private", conditions())
    journal = PagedJournal()
    controls = remove(engine, actor, plan, kind, journal)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE plans SET conditions=CAST(:value AS jsonb) WHERE id=:id"),
            dict(id=plan.id, value=conditions().canonical_json()),
        )
        connection.execute(
            text(
                "UPDATE discovery_commands SET result=jsonb_build_object("
                "'generation',:generation,'conditions_revision',1,"
                "'conditions',CAST(:value AS jsonb)) WHERE target_id=:id"
            ),
            dict(
                id=plan.id,
                generation=actor.generation,
                value=conditions().canonical_json(),
            ),
        )
    reconcile_control_log(journal, controls)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT conditions FROM plans WHERE id=:id"), dict(id=plan.id)
            )
            == {}
        )
        assert (
            connection.scalar(
                text(
                    "SELECT result ? 'conditions' FROM discovery_commands "
                    "WHERE target_id=:id"
                ),
                dict(id=plan.id),
            )
            is False
        )


@pytest.mark.parametrize("kind", ["plan", "actor"])
def test_purge_requires_a_closed_parent_scope(plan_context, kind):
    engine, store, (actor, _) = plan_context
    plan = store.create(actor.id, actor.generation, "private", conditions())
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="fence"):
            if kind == "plan":
                purge_plan_originals(connection, actor.id, actor.generation, plan.id)
            else:
                purge_actor_plan_originals(connection, actor.id, actor.generation)
    assert store.read(plan.id, actor.id) == plan


def test_cleanup_failure_rolls_back_plan_fence_and_originals(plan_context, monkeypatch):
    engine, store, (actor, _) = plan_context
    plan = store.create(actor.id, actor.generation, "private", conditions())
    original = control_module.purge_plan_originals

    def fail(connection, owner, generation, target):
        original(connection, owner, generation, target)
        raise RuntimeError("synthetic plan scrub failure")

    monkeypatch.setattr(control_module, "purge_plan_originals", fail)
    with pytest.raises(RuntimeError, match="synthetic plan scrub failure"):
        remove(engine, actor, plan)
    assert store.read(plan.id, actor.id) == plan
    assert store.create(actor.id, actor.generation, "private", conditions()) == plan
