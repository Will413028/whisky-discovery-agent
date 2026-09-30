from uuid import uuid4

import pytest
from sqlalchemy import text
from test_comparison_reports_v4 import comparison_commit as comparison_commit

from whisky.modules.research.inputs_v4 import (
    ResearchInputV4,
    StartCommandV4,
    StartTurnV4,
)
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.store import ResearchConflict

pytestmark = pytest.mark.integration


def test_restart_rejects_an_unknown_source_before_reserving_a_task(comparison_commit):
    _, research, actor, commit, comparison = comparison_commit
    ReportStore(research.engine).save_v4(commit, comparison)
    source = research.task(commit.task_id, actor.id)
    command = StartCommandV4(
        type="start_v4",
        key="restart",
        plan_id=source_plan(research, source.task_id),
        conditions_revision=1,
        input=ResearchInputV4(),
    ).model_copy(update={"source_task_id": uuid4()})
    with pytest.raises(ResearchConflict, match="NOT_FOUND"):
        research.reserve_turn_v4(
            actor.id, actor.generation, StartTurnV4(uuid4(), uuid4(), command)
        )


def source_plan(research, task_id):
    with research.engine.connect() as connection:
        return connection.scalar(
            text("SELECT plan_id FROM research_tasks WHERE id=:task"), {"task": task_id}
        )


def test_restart_source_is_atomic_immutable_and_uses_current_conditions(
    comparison_commit,
):
    engine, research, actor, commit, comparison = comparison_commit
    saved = ReportStore(engine).save_v4(commit, comparison)
    plan_id = source_plan(research, commit.task_id)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE plans SET conditions_revision=2,"
                "conditions=jsonb_set(conditions,'{budget_twd}','\"900\"') "
                "WHERE id=:plan"
            ),
            {"plan": plan_id},
        )
    command = StartCommandV4(
        type="start_v4",
        key="linked-restart",
        plan_id=plan_id,
        conditions_revision=2,
        input=ResearchInputV4(intent=comparison.intent),
        source_task_id=commit.task_id,
    )
    turn = StartTurnV4(uuid4(), uuid4(), command)
    receipt = research.reserve_turn_v4(actor.id, actor.generation, turn)
    assert receipt.task_id != saved.task_id
    assert research.reserve_turn_v4(actor.id, actor.generation, turn) == receipt
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT source_task_id FROM research_v4_inputs WHERE task_id=:task"
                ),
                {"task": receipt.task_id},
            )
            == commit.task_id
        )
        snapshot = connection.execute(
            text(
                "SELECT conditions_revision,conditions FROM research_tasks "
                "WHERE id=:task"
            ),
            {"task": receipt.task_id},
        ).one()
        assert snapshot.conditions_revision == 2
        assert snapshot.conditions["budget_twd"] == "900"
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM research_v4_inputs "
                    "WHERE source_task_id=:source"
                ),
                {"source": commit.task_id},
            )
            == 1
        )
    changed = StartTurnV4(
        turn.thread_id, turn.run_id, command.model_copy(update={"source_task_id": None})
    )
    with pytest.raises(ResearchConflict, match="IDEMPOTENCY_CONFLICT"):
        research.reserve_turn_v4(actor.id, actor.generation, changed)
    assert ReportStore(engine).read(actor.id, saved.id).conditions_revision == 1


@pytest.mark.parametrize(
    "mutation", ["foreign", "other_plan", "unfinished", "old_generation"]
)
def test_restart_never_adopts_an_ineligible_source(comparison_commit, mutation):
    engine, research, actor, commit, comparison = comparison_commit
    ReportStore(engine).save_v4(commit, comparison)
    plan_id = source_plan(research, commit.task_id)
    with engine.begin() as connection:
        if mutation == "foreign":
            # A known but unrelated task ID is still unavailable to another owner.
            from whisky.modules.discovery.conditions import ResearchConditions
            from whisky.modules.discovery.store import PlanStore
            from whisky.modules.identity.store import IdentityStore
            from whisky.modules.identity.tokens import Principal

            other = IdentityStore(engine).resolve(
                Principal("https://fixture.example/", "foreign")
            )
            foreign_plan = PlanStore(engine).create(
                other.id,
                other.generation,
                "foreign",
                ResearchConditions(goal="合成", entry="beginner"),
            )
            target_owner, target_generation, plan_id = (
                other.id,
                other.generation,
                foreign_plan.id,
            )
        else:
            target_owner, target_generation = actor.id, actor.generation
            if mutation == "other_plan":
                from whisky.modules.discovery.conditions import ResearchConditions
                from whisky.modules.discovery.store import PlanStore

                plan_id = (
                    PlanStore(engine)
                    .create(
                        actor.id,
                        actor.generation,
                        "different",
                        ResearchConditions(goal="合成", entry="beginner"),
                    )
                    .id
                )
            elif mutation == "unfinished":
                connection.execute(
                    text(
                        "UPDATE research_tasks SET status='researching',report_id=NULL "
                        "WHERE id=:task"
                    ),
                    {"task": commit.task_id},
                )
            else:
                connection.execute(
                    text("UPDATE users SET generation=generation+1 WHERE id=:owner"),
                    {"owner": actor.id},
                )
                connection.execute(
                    text("UPDATE plans SET generation=generation+1 WHERE id=:plan"),
                    {"plan": plan_id},
                )
                target_generation += 1
    command = StartCommandV4(
        type="start_v4",
        key="refused-source",
        plan_id=plan_id,
        conditions_revision=1,
        input=ResearchInputV4(),
        source_task_id=commit.task_id,
    )
    with pytest.raises(ResearchConflict, match="NOT_FOUND"):
        research.reserve_turn_v4(
            target_owner, target_generation, StartTurnV4(uuid4(), uuid4(), command)
        )
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM research_commands WHERE key='refused-source'"
                )
            )
            == 0
        )
