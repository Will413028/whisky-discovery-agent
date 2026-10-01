from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_preference_proposal_publication import prepare

from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.proposal_view_v4 import read_preference_proposal_v4

pytestmark = pytest.mark.integration


@pytest.fixture
def visible_proposal(research_context):
    engine, store, actor, plan, context, source, draft = prepare(research_context)
    question = ClarificationStore(engine).publish_preference_proposal(
        context, 1, source, draft, datetime.now(UTC) + timedelta(days=7)
    )
    return engine, actor, plan, context.task_id, question, source, draft


def test_visible_draft_is_bound_to_its_exact_active_question(visible_proposal):
    engine, actor, _, task_id, question, source, draft = visible_proposal
    view = read_preference_proposal_v4(engine, actor.id, task_id)
    assert view is not None
    assert view.task_id == task_id and view.question_id == question.id
    assert view.waiting_version == 1 and view.conditions_revision == 1
    assert view.source_text == source and view.proposal == draft


@pytest.mark.parametrize(
    "change",
    [
        "kind",
        "active_question",
        "expired",
        "answered",
        "cancelled",
        "revision",
        "generation",
    ],
)
def test_draft_cannot_escape_question_revision_or_identity_fences(
    visible_proposal, change
):
    engine, actor, plan, task_id, question, _, _ = visible_proposal
    assert read_preference_proposal_v4(engine, actor.id, task_id) is not None
    commands = {
        "kind": "UPDATE clarifications SET kind='version' WHERE id=:question",
        "active_question": (
            "UPDATE research_tasks SET status='researching',"
            "active_question_id=NULL,question=NULL WHERE id=:task"
        ),
        "expired": (
            "UPDATE clarifications SET expires_at=now()-interval '1 second' "
            "WHERE id=:question"
        ),
        "cancelled": (
            "UPDATE research_tasks SET status='cancelled',write_allowed=false,"
            "active_question_id=NULL,question=NULL WHERE id=:task"
        ),
        "revision": (
            "UPDATE plans SET conditions_revision=conditions_revision+1 WHERE id=:plan"
        ),
        "generation": "UPDATE users SET generation=generation+1 WHERE id=:owner",
    }
    if change == "answered":
        questions = ClarificationStore(engine)
        with engine.connect() as connection:
            choices = connection.scalar(
                text("SELECT choices FROM clarifications WHERE id=:question"),
                {"question": question.id},
            )
        receipt = questions.reserve_answer(
            actor.id,
            actor.generation,
            task_id,
            question.id,
            1,
            1,
            "read-test-answer",
            choices[0]["id"],
        )
        questions.accept_answer(receipt)
        assert read_preference_proposal_v4(engine, actor.id, task_id) is None
        return
    with engine.begin() as connection:
        connection.execute(
            text(commands[change]),
            dict(question=question.id, task=task_id, plan=plan.id, owner=actor.id),
        )
    assert read_preference_proposal_v4(engine, actor.id, task_id) is None


def test_draft_read_is_owner_scoped_and_missing_is_indistinguishable(
    visible_proposal, research_context
):
    engine, actor, _, task_id, _, _, _ = visible_proposal
    _, _, (_, foreign), _ = research_context
    assert read_preference_proposal_v4(engine, foreign.id, task_id) is None
    assert read_preference_proposal_v4(engine, actor.id, uuid4()) is None
