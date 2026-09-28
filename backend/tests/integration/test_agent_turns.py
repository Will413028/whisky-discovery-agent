from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import text

from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.research.commands import StartCommand, StartTurn
from whisky.modules.research.store import ResearchConflict

pytestmark = pytest.mark.integration


def turn(plan, *, thread=None, run=None, key="first", revision=1):
    return StartTurn(
        thread or uuid4(),
        run or uuid4(),
        StartCommand(
            type="start", key=key, plan_id=plan.id, conditions_revision=revision
        ),
    )


def test_start_turn_replay_keeps_task_thread_and_command(research_context):
    engine, store, (actor, _), plan = research_context
    request = turn(plan)
    first = store.reserve_turn(actor.id, actor.generation, request)
    assert store.reserve_turn(actor.id, actor.generation, request) == first
    assert store.task(first.task_id, actor.id).thread_id == request.thread_id
    with engine.connect() as connection:
        row = connection.execute(text("SELECT * FROM agent_turns")).mappings().one()
        assert row["command_id"] == first.id and row["task_id"] == first.task_id
        assert row["run_id"] == request.run_id and row["outcome"] is None


@pytest.mark.parametrize("change", ["key", "run", "thread", "revision"])
def test_changed_turn_binding_is_rejected_without_extra_task(research_context, change):
    engine, store, (actor, _), plan = research_context
    request = turn(plan)
    store.reserve_turn(actor.id, actor.generation, request)
    kwargs = {"thread": request.thread_id, "run": request.run_id}
    kwargs[change] = (
        2 if change == "revision" else "other" if change == "key" else uuid4()
    )
    with pytest.raises(ResearchConflict):
        store.reserve_turn(actor.id, actor.generation, turn(plan, **kwargs))
    with engine.connect() as connection:
        for table in ["research_tasks", "research_commands", "agent_turns"]:
            assert (
                connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                == 1
            )


def test_parallel_turn_has_one_binding(research_context):
    engine, store, (actor, _), plan = research_context
    request = turn(plan)
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(
            executor.map(
                lambda _: store.reserve_turn(actor.id, actor.generation, request),
                range(2),
            )
        )
    assert receipts[0] == receipts[1]
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM agent_turns")).scalar_one()
            == 1
        )


def test_client_thread_id_is_owner_scoped(research_context):
    engine, store, (actor, other), plan = research_context
    other_plan = PlanStore(engine).create(
        other.id,
        other.generation,
        "other-plan",
        ResearchConditions(entry="beginner", goal="other"),
    )
    request = turn(plan)
    first = store.reserve_turn(actor.id, actor.generation, request)
    second = store.reserve_turn(
        other.id,
        other.generation,
        turn(other_plan, thread=request.thread_id, run=request.run_id),
    )
    assert first.task_id != second.task_id
    assert store.task(second.task_id, actor.id) is None


def test_turn_insert_failure_rolls_back_task_and_receipt(research_context):
    engine, store, (actor, _), plan = research_context
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE agent_turns ADD CONSTRAINT fixture_fail CHECK (false)")
        )
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        store.reserve_turn(actor.id, actor.generation, turn(plan))
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM research_tasks")).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM research_commands")
            ).scalar_one()
            == 0
        )
