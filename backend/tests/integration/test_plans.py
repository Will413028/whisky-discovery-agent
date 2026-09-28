from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from test_catalog_release import synthetic_release

from whisky.bootstrap.migrate import upgrade
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanConflict, PlanStore
from whisky.modules.identity.store import IdentityStore
from whisky.modules.identity.tokens import Principal

pytestmark = pytest.mark.integration


@pytest.fixture
def plan_context(postgres_url):
    engine = create_engine(postgres_url)
    try:
        upgrade(engine, Path(__file__).parents[2] / "migrations")
        actors = [
            IdentityStore(engine).resolve(
                Principal("https://fixture.example/", subject)
            )
            for subject in ("one", "two")
        ]
        yield engine, PlanStore(engine), actors
    finally:
        engine.dispose()


def conditions(**changes):
    return ResearchConditions(entry="beginner", goal="探索果香", **changes)


def test_same_key_and_normalized_payload_return_original_plan(plan_context):
    engine, store, (actor, _) = plan_context
    first = store.create(
        actor.id, actor.generation, "create-1", conditions(budget_twd="1000")
    )
    assert first is not None, "accepted plan must be persisted"
    again = store.create(
        actor.id, actor.generation, "create-1", conditions(budget_twd="1000.00")
    )
    assert first == again == store.read(first.id, actor.id)
    assert first.conditions_revision == 1
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM plans")) == 1
        assert connection.scalar(text("SELECT count(*) FROM discovery_commands")) == 1


def test_same_key_different_payload_conflicts(plan_context):
    _, store, (actor, _) = plan_context
    store.create(actor.id, actor.generation, "one", conditions())
    with pytest.raises(PlanConflict, match="IDEMPOTENCY_CONFLICT"):
        store.create(actor.id, actor.generation, "one", conditions(budget_twd="999"))


def test_create_receipt_replays_original_result_after_plan_changes(plan_context):
    engine, store, (actor, _) = plan_context
    original = store.create(actor.id, actor.generation, "original", conditions())
    with engine.begin() as connection:
        connection.execute(
            text("""
            UPDATE plans SET conditions_revision = 2,
                conditions = CAST(:conditions AS jsonb) WHERE id = :id
        """),
            dict(
                id=original.id, conditions=conditions(budget_twd="999").canonical_json()
            ),
        )
    assert store.read(original.id, actor.id).conditions_revision == 2
    assert (
        store.create(actor.id, actor.generation, "original", conditions()) == original
    )


def test_keys_and_reads_are_scoped_to_owner(plan_context):
    _, store, (first, second) = plan_context
    one = store.create(first.id, first.generation, "shared", conditions())
    two = store.create(second.id, second.generation, "shared", conditions())
    assert one is not None and two is not None
    assert one.id != two.id
    assert store.read(one.id, second.id) is None
    assert store.read(two.id, first.id) is None


@pytest.mark.parametrize("change", ["generation = 2", "active = false"])
def test_stale_or_disabled_identity_cannot_create_or_replay(plan_context, change):
    engine, store, (actor, _) = plan_context
    store.create(actor.id, actor.generation, "old", conditions())
    with engine.begin() as connection:
        connection.execute(
            text(f"UPDATE users SET {change} WHERE id = :id"), {"id": actor.id}
        )
    for key in ("old", "new"):
        with pytest.raises(PlanConflict, match="IDENTITY_CHANGED"):
            store.create(actor.id, actor.generation, key, conditions())


def test_concurrent_create_has_one_receipt_and_one_plan(plan_context):
    engine, store, (actor, _) = plan_context
    barrier = Barrier(2)

    def create(_):
        barrier.wait(timeout=10)
        return store.create(actor.id, actor.generation, "race", conditions())

    with ThreadPoolExecutor(max_workers=2) as executor:
        plans = list(executor.map(create, range(2)))
    assert plans[0] is not None and plans[0] == plans[1]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM plans")) == 1
        assert connection.scalar(text("SELECT count(*) FROM discovery_commands")) == 1


def test_plan_starting_bottle_must_resolve_in_published_catalog(plan_context):
    engine, store, (actor, _) = plan_context
    value = ResearchConditions(
        entry="existing_bottle",
        goal="保留果香",
        starting_bottle=dict(release_id=uuid4(), item_id=uuid4()),
    )
    with pytest.raises(PlanConflict, match="CATALOG_REFERENCE_NOT_FOUND"):
        store.create(actor.id, actor.generation, "reference", value)
    release = synthetic_release()
    CatalogStore(engine).publish(release)
    value = ResearchConditions(
        entry="existing_bottle",
        goal="保留果香",
        starting_bottle=dict(release_id=release.id, item_id=release.items[0].id),
    )
    assert (
        store.create(actor.id, actor.generation, "reference", value).conditions == value
    )


def test_failure_between_receipt_and_plan_rolls_back_both(plan_context):
    engine, store, (actor, _) = plan_context

    def interrupt(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "INSERT INTO plans" in statement:
            raise RuntimeError("injected before plan insert")

    event.listen(engine, "before_cursor_execute", interrupt)
    try:
        with pytest.raises(RuntimeError, match="before plan insert"):
            store.create(actor.id, actor.generation, "interrupted", conditions())
    finally:
        event.remove(engine, "before_cursor_execute", interrupt)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM plans")) == 0
        assert connection.scalar(text("SELECT count(*) FROM discovery_commands")) == 0
    assert (
        store.create(actor.id, actor.generation, "interrupted", conditions())
        is not None
    )


def test_database_rejects_receipt_pointing_at_another_owners_plan(plan_context):
    engine, store, (actor, other) = plan_context
    store.create(actor.id, actor.generation, "owner-fk", conditions())
    with pytest.raises(IntegrityError) as error:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE discovery_commands SET owner_id = :owner"),
                dict(owner=other.id),
            )
    assert error.value.orig.sqlstate == "23503"


def test_plan_pages_use_timestamp_and_id_without_repeating_rows(plan_context):
    engine, store, (actor, other) = plan_context
    plans = [
        store.create(actor.id, actor.generation, f"page-{i}", conditions())
        for i in range(5)
    ]
    store.create(other.id, other.generation, "foreign", conditions())
    with engine.begin() as connection:
        connection.execute(text("UPDATE plans SET updated_at = '2026-09-28T00:00:00Z'"))
    first = store.page(actor.id, limit=2)
    assert len(first.items) == 2
    assert first.next_cursor is not None
    second = store.page(actor.id, limit=2, cursor=first.next_cursor)
    third = store.page(actor.id, limit=2, cursor=second.next_cursor)
    assert len(second.items) == 2 and len(third.items) == 1
    assert third.next_cursor is None
    assert [plan.id for plan in (*first.items, *second.items, *third.items)] == sorted(
        (plan.id for plan in plans), reverse=True
    )


@pytest.mark.parametrize("limit", [0, -1, 51])
def test_plan_page_limit_is_bounded(plan_context, limit):
    _, store, (actor, _) = plan_context
    with pytest.raises(ValueError, match="limit"):
        store.page(actor.id, limit=limit)


@pytest.mark.parametrize("change", ["active = false", "generation = 2"])
def test_plan_pages_hide_disabled_or_previous_generation_data(plan_context, change):
    engine, store, (actor, _) = plan_context
    store.create(actor.id, actor.generation, "private-page", conditions())
    assert store.page(actor.id).items
    with engine.begin() as connection:
        connection.execute(
            text(f"UPDATE users SET {change} WHERE id = :id"), dict(id=actor.id)
        )
    assert store.page(actor.id).items == ()
