from uuid import uuid4

import pytest

from whisky.modules.research.inputs_v4 import (
    ResearchInputV4,
    StartCommandV4,
    StartTurnV4,
)
from whisky.modules.research.run_store import ResearchRunStore
from whisky.modules.research.store import ResearchConflict

pytestmark = pytest.mark.integration


def test_begin_v4_returns_the_persisted_input_and_confirmed_plan_snapshot(
    research_context,
):
    engine, store, (actor, _), plan = research_context
    original = ResearchInputV4(phase="proposal", source_text="我喜歡甜點")
    turn = StartTurnV4(
        uuid4(),
        uuid4(),
        StartCommandV4(
            type="start_v4",
            key="execution",
            plan_id=plan.id,
            conditions_revision=1,
            input=original,
        ),
    )
    receipt = store.reserve_turn_v4(actor.id, actor.generation, turn)
    execution = ResearchRunStore(engine).begin_v4(receipt.task_id, "fixture-v4-pinned")
    assert execution.input == original
    assert execution.context.conditions == plan.conditions
    assert execution.context.prompt_version == "fixture-v4-pinned"
    assert store.task(receipt.task_id, actor.id).status == "researching"


def test_v4_cannot_silently_use_a_legacy_task_or_commit_a_partial_begin(
    research_context,
):
    engine, store, (actor, _), plan = research_context
    receipt = store.reserve(actor.id, actor.generation, plan.id, 1, "legacy")
    before = store.task(receipt.task_id, actor.id)
    with pytest.raises(ResearchConflict, match="V4_INPUT_NOT_FOUND"):
        ResearchRunStore(engine).begin_v4(receipt.task_id, "fixture-v4-pinned")
    after = store.task(receipt.task_id, actor.id)
    assert after.status == before.status
    assert after.view_version == before.view_version
