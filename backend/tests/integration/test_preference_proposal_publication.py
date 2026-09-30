"""A model draft and human question are published under the same task fence."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from whisky.modules.discovery.proposal import PreferenceProposal, PreferenceSuggestion
from whisky.modules.discovery.store import PlanStore
from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.inputs_v4 import (
    ResearchInputV4,
    StartCommandV4,
    StartTurnV4,
)
from whisky.modules.research.report import ReportDraft
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.run_store import ResearchRunStore
from whisky.modules.research.store import ResearchConflict

pytestmark = pytest.mark.integration


def prepare(research_context):
    engine, store, (actor, _), plan = research_context
    source = "我喜歡甜點，但還不知道喜歡什麼威士忌"
    turn = StartTurnV4(
        uuid4(),
        uuid4(),
        StartCommandV4(
            type="start_v4",
            key="proposal",
            plan_id=plan.id,
            conditions_revision=1,
            input=ResearchInputV4(phase="proposal", source_text=source),
        ),
    )
    receipt = store.reserve_turn_v4(actor.id, actor.generation, turn)
    context = ResearchRunStore(engine).begin(receipt.task_id)
    draft = PreferenceProposal(
        summary="甜香只是待確認線索",
        preferences=(
            PreferenceSuggestion(
                description="甜香",
                intent="prefer",
                source_quote="喜歡甜點",
                source_kind="food_clue",
            ),
        ),
    )
    return engine, store, actor, plan, context, source, draft


@pytest.mark.parametrize("summary", ["甜香只是待確認線索", "甲" * 1600])
def test_proposal_and_question_commit_together_without_changing_confirmed_conditions(
    research_context,
    summary,
):
    engine, store, actor, plan, context, source, draft = prepare(research_context)
    draft = draft.model_copy(update={"summary": summary})
    questions = ClarificationStore(engine)
    expiry = datetime.now(UTC) + timedelta(days=7)
    question = questions.publish_preference_proposal(context, 1, source, draft, expiry)
    assert (
        questions.publish_preference_proposal(context, 1, source, draft, expiry)
        == question
    )
    task = store.task(context.task_id, actor.id)
    assert (
        task is not None
        and task.status == "needs_input"
        and task.question.id == question.id
    )
    assert len(task.question.choices) == 2
    assert task.question.prompt.startswith(summary)
    assert len(task.question.prompt) <= 2000
    with engine.connect() as connection:
        row = (
            connection.execute(
                text("SELECT * FROM preference_proposals WHERE task_id=:task"),
                {"task": context.task_id},
            )
            .mappings()
            .one()
        )
        assert row["source_text"] == source
        assert row["proposal"]["preferences"][0]["certainty"] == "inferred"
        assert (
            connection.scalar(
                text("SELECT kind FROM clarifications WHERE id=:id"),
                {"id": question.id},
            )
            == "preference_proposal"
        )
    unchanged = PlanStore(engine).read(plan.id, actor.id)
    assert (
        unchanged.conditions == plan.conditions and unchanged.conditions_revision == 1
    )


def test_a_proposal_answer_is_not_reported_as_a_confirmed_bottle_version(
    research_context,
):
    engine, store, actor, _, context, source, draft = prepare(research_context)
    questions = ClarificationStore(engine)
    question = questions.publish_preference_proposal(
        context, 1, source, draft, datetime.now(UTC) + timedelta(days=7)
    )
    task = store.task(context.task_id, actor.id)
    answer = questions.reserve_answer(
        actor.id,
        actor.generation,
        context.task_id,
        question.id,
        1,
        1,
        "continue",
        str(task.question.choices[0].id),
    )
    assert questions.accept_answer(answer).acceptance == "accepted"
    saved = ReportStore(engine).save(
        actor.id,
        actor.generation,
        context.task_id,
        "proposal-answer",
        ReportDraft(summary="依原條件研究", candidates=()),
        policy_version=context.policy_version,
        prompt_version="fixture-v4",
        model_version="fixture-v4",
    )
    view = ReportStore(engine).read(actor.id, saved.id)
    assert view.clarified_bottle is None


def test_cancelled_task_cannot_publish_late_proposal(research_context):
    engine, _, _, _, context, source, draft = prepare(research_context)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE research_tasks SET status='cancelled',write_allowed=false "
                "WHERE id=:id"
            ),
            {"id": context.task_id},
        )
    with pytest.raises(ResearchConflict, match="TASK_NOT_WRITABLE"):
        ClarificationStore(engine).publish_preference_proposal(
            context, 1, source, draft, datetime.now(UTC) + timedelta(days=7)
        )
