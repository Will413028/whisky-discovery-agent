"""V4 start snapshots every confirmed input under one durable receipt."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from whisky.modules.discovery.public import ExplorationIntent
from whisky.modules.research.inputs_v4 import (
    ResearchInputV4,
    StartCommandV4,
    StartTurnV4,
)
from whisky.modules.research.store import ResearchConflict

pytestmark = pytest.mark.integration


def make_turn(plan, key="v4-start", **values):
    return StartTurnV4(
        uuid4(),
        uuid4(),
        StartCommandV4(
            type="start_v4",
            key=key,
            plan_id=plan.id,
            conditions_revision=1,
            input=ResearchInputV4(**values),
        ),
    )


def test_v4_input_and_agui_binding_commit_with_one_receipt(research_context):
    engine, store, (actor, _), plan = research_context
    turn = make_turn(
        plan, intent=ExplorationIntent(mode="similar", origin_query="合成起點")
    )
    receipt = store.reserve_turn_v4(actor.id, actor.generation, turn)
    replay = store.reserve_turn_v4(actor.id, actor.generation, turn)
    assert receipt == replay
    with engine.connect() as connection:
        row = (
            connection.execute(
                text("SELECT * FROM research_v4_inputs WHERE task_id=:id"),
                {"id": receipt.task_id},
            )
            .mappings()
            .one()
        )
        assert ResearchInputV4.model_validate(row["input"]) == turn.command.input
        binding = connection.execute(
            text("SELECT thread_id,run_id FROM agent_turns WHERE command_id=:id"),
            {"id": receipt.id},
        ).one()
        assert (binding.thread_id, binding.run_id) == (turn.thread_id, turn.run_id)
        assert connection.scalar(text("SELECT count(*) FROM research_v4_inputs")) == 1
    view = store.task(receipt.task_id, actor.id)
    assert view is not None and view.conditions_revision == 1


@pytest.mark.parametrize(
    "replacement",
    [
        ResearchInputV4(intent=ExplorationIntent(mode="contrast")),
        ResearchInputV4(phase="proposal", source_text="我喜歡甜點"),
    ],
)
def test_same_key_cannot_change_intent_or_proposal_source(
    research_context, replacement
):
    _, store, (actor, _), plan = research_context
    turn = make_turn(plan)
    original = store.reserve_turn_v4(actor.id, actor.generation, turn)
    changed = StartTurnV4(
        turn.thread_id,
        turn.run_id,
        turn.command.model_copy(update={"input": replacement}),
    )
    with pytest.raises(ResearchConflict, match="IDEMPOTENCY_CONFLICT"):
        store.reserve_turn_v4(actor.id, actor.generation, changed)
    assert store.reserve_turn_v4(actor.id, actor.generation, turn) == original


def test_v4_and_legacy_start_keys_never_alias(research_context):
    _, store, (actor, _), plan = research_context
    old = store.reserve(actor.id, actor.generation, plan.id, 1, "shared")
    with pytest.raises(ResearchConflict, match="IDEMPOTENCY_CONFLICT"):
        store.reserve_turn_v4(actor.id, actor.generation, make_turn(plan, "shared"))
    assert store.reserve(actor.id, actor.generation, plan.id, 1, "shared") == old


def test_proposal_source_is_immutable_even_when_phase_and_mode_stay_the_same(
    research_context,
):
    _, store, (actor, _), plan = research_context
    turn = make_turn(plan, phase="proposal", source_text="我喜歡甜點")
    original = store.reserve_turn_v4(actor.id, actor.generation, turn)
    changed = StartTurnV4(
        turn.thread_id,
        turn.run_id,
        turn.command.model_copy(
            update={
                "input": ResearchInputV4(phase="proposal", source_text="我不喜歡甜點")
            }
        ),
    )
    with pytest.raises(ResearchConflict, match="IDEMPOTENCY_CONFLICT"):
        store.reserve_turn_v4(actor.id, actor.generation, changed)
    assert store.reserve_turn_v4(actor.id, actor.generation, turn) == original


def test_v4_start_keeps_owner_revision_and_turn_fences(research_context):
    _, store, (actor, foreign), plan = research_context
    turn = make_turn(plan)
    with pytest.raises(ResearchConflict, match="NOT_FOUND"):
        store.reserve_turn_v4(foreign.id, foreign.generation, turn)
    wrong = StartTurnV4(
        turn.thread_id,
        turn.run_id,
        turn.command.model_copy(update={"conditions_revision": 2}),
    )
    with pytest.raises(ResearchConflict, match="REVISION_CONFLICT"):
        store.reserve_turn_v4(actor.id, actor.generation, wrong)
    store.reserve_turn_v4(actor.id, actor.generation, turn)
    with pytest.raises(ResearchConflict, match="TURN_CONFLICT"):
        store.reserve_turn_v4(
            actor.id,
            actor.generation,
            StartTurnV4(turn.thread_id, uuid4(), turn.command),
        )
