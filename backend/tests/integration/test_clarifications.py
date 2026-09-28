"""Question publication persists the task-facing wait before Temporal suspends."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from test_catalog_release import synthetic_release, synthetic_versioned_release

from whisky.modules.catalog.store import CatalogStore
from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.decision import ClarificationDraft
from whisky.modules.research.report import ReportCandidate, ReportClaim, ReportDraft
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.run_store import ResearchRunStore
from whisky.modules.research.store import ResearchConflict

pytestmark = pytest.mark.integration


def published_choices(engine):
    release = synthetic_versioned_release()
    CatalogStore(engine).publish(release)
    return tuple(str(item.bottle.version_id) for item in release.items)


def test_question_choices_are_reviewed_version_ids_with_server_labels(research_context):
    engine, research, (actor, _), plan = research_context
    release = synthetic_versioned_release()
    CatalogStore(engine).publish(release)
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "version-choice")
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    context = ResearchRunStore(engine).begin(receipt.task_id)
    store = ClarificationStore(engine)
    with pytest.raises(ValueError, match="INVALID_VERSION_CHOICE"):
        store.publish(
            context,
            1,
            ClarificationDraft(
                "哪個版本？", (str(uuid4()), str(release.items[1].bottle.version_id))
            ),
            datetime.now(UTC) + timedelta(days=7),
        )
    question = store.publish(
        context,
        1,
        ClarificationDraft(
            "哪個版本？", tuple(str(item.bottle.version_id) for item in release.items)
        ),
        datetime.now(UTC) + timedelta(days=7),
    )
    view = research.task(receipt.task_id, actor.id)
    assert view.question is not None and view.question.id == question.id
    assert [(str(choice.id), choice.label) for choice in view.question.choices] == [
        (str(item.bottle.version_id), item.name) for item in release.items
    ]


def test_report_requires_the_accepted_version_and_records_current_resolution(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    release = synthetic_versioned_release()
    CatalogStore(engine).publish(release)
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "version-report")
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    context = ResearchRunStore(engine).begin(receipt.task_id)
    store = ClarificationStore(engine)
    selected = release.items[1]
    question = store.publish(
        context,
        1,
        ClarificationDraft(
            "哪個版本？", tuple(str(item.bottle.version_id) for item in release.items)
        ),
        datetime.now(UTC) + timedelta(days=7),
    )
    answer = store.reserve_answer(
        actor.id,
        actor.generation,
        receipt.task_id,
        question.id,
        1,
        1,
        "version-reply",
        str(selected.bottle.version_id),
    )
    assert store.accept_answer(answer).acceptance == "accepted"
    reports = ReportStore(engine)
    arguments = dict(
        policy_version="price-30d-v1",
        prompt_version="research-v2",
        model_version="fixture",
    )
    with pytest.raises(ResearchConflict, match="CLARIFICATION_MISMATCH"):
        reports.save(
            actor.id,
            actor.generation,
            receipt.task_id,
            "missing-version",
            ReportDraft("已核對", ()),
            **arguments,
        )
    with pytest.raises(ResearchConflict, match="CLARIFICATION_MISMATCH"):
        reports.save(
            actor.id,
            actor.generation,
            receipt.task_id,
            "wrong-version",
            ReportDraft("已核對", ()),
            clarification_id=question.id,
            selected_version_id=release.items[0].bottle.version_id,
            **arguments,
        )
    saved = reports.save(
        actor.id,
        actor.generation,
        receipt.task_id,
        "matched-version",
        ReportDraft("已核對", ()),
        clarification_id=question.id,
        selected_version_id=selected.bottle.version_id,
        **arguments,
    )
    view = reports.read(actor.id, saved.id)
    assert view is not None and view.clarified_bottle is not None
    assert view.clarified_bottle.bottle_version_id == selected.bottle.version_id
    assert view.clarified_bottle.name == selected.name
    assert view.clarified_bottle.reviewed_in_release is True


def test_removed_version_cannot_be_replaced_by_an_unrelated_current_bottle(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    prior = synthetic_versioned_release()
    CatalogStore(engine).publish(prior)
    receipt = research.reserve(
        actor.id, actor.generation, plan.id, 1, "removed-version"
    )
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    context = ResearchRunStore(engine).begin(receipt.task_id)
    store = ClarificationStore(engine)
    selected = prior.items[1].bottle.version_id
    question = store.publish(
        context,
        1,
        ClarificationDraft(
            "哪個版本？", tuple(str(item.bottle.version_id) for item in prior.items)
        ),
        datetime.now(UTC) + timedelta(days=7),
    )
    answer = store.reserve_answer(
        actor.id,
        actor.generation,
        receipt.task_id,
        question.id,
        1,
        1,
        "removed-answer",
        str(selected),
    )
    assert store.accept_answer(answer).acceptance == "accepted"
    current = synthetic_release()
    current = replace(current, published_at=prior.published_at + timedelta(days=1))
    CatalogStore(engine).publish(current)
    item = current.items[0]
    fact = item.facts[0]
    draft = ReportDraft(
        "錯誤地把別款當成所選版本",
        (
            ReportCandidate(
                current.id,
                item.id,
                (ReportClaim("fact", fact.field, fact.value, fact.evidence_ids),),
                "不是該版本",
            ),
        ),
    )
    saved = ReportStore(engine).save(
        actor.id,
        actor.generation,
        receipt.task_id,
        "removed-report",
        draft,
        policy_version="price-30d-v1",
        prompt_version="research-v2",
        model_version="fixture",
        clarification_id=question.id,
        selected_version_id=selected,
    )
    report = ReportStore(engine).read(actor.id, saved.id)
    assert report is not None and report.candidates == ()
    assert report.clarified_bottle is not None
    assert report.clarified_bottle.reviewed_in_release is False
    assert report.unresolved and "reviewed catalog" in report.unresolved[0]


def test_question_publication_is_recoverable_and_idempotent(
    research_context, monkeypatch
):
    engine, research, (actor, _), plan = research_context
    choices = published_choices(engine)
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "question")
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    context = ResearchRunStore(engine).begin(receipt.task_id)
    draft = ClarificationDraft("你指的是哪個版本？", choices)
    expires_at = datetime.now(UTC) + timedelta(days=7)
    store = ClarificationStore(engine)

    question = store.publish(context, 1, draft, expires_at)
    task = research.task(receipt.task_id, actor.id)
    assert task.status == "needs_input"
    assert task.question is not None
    assert task.question.id == question.id
    assert task.question.waiting_version == 1
    assert task.question.prompt == draft.prompt
    assert tuple(str(choice.id) for choice in task.question.choices) == draft.choices
    newer = synthetic_release()
    CatalogStore(engine).publish(
        replace(newer, published_at=datetime.now(UTC) - timedelta(seconds=1))
    )

    class AfterExpiry(datetime):
        @classmethod
        def now(cls, tz=None):
            return expires_at + timedelta(seconds=1)

    monkeypatch.setattr("whisky.modules.research.clarification.datetime", AfterExpiry)
    assert store.publish(context, 1, draft, expires_at) == question
    assert research.task(receipt.task_id, actor.id).view_version == task.view_version


def test_answer_receipt_is_idempotent_and_resumes_the_same_task(research_context):
    engine, research, (actor, _), plan = research_context
    choices = published_choices(engine)
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "question")
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    context = ResearchRunStore(engine).begin(receipt.task_id)
    store = ClarificationStore(engine)
    question = store.publish(
        context,
        1,
        ClarificationDraft("你指的是哪個版本？", choices),
        datetime.now(UTC) + timedelta(days=7),
    )

    answer = store.reserve_answer(
        actor.id,
        actor.generation,
        receipt.task_id,
        question.id,
        1,
        1,
        "answer-once",
        choices[1],
    )
    assert answer.acceptance == "acceptance_pending"
    assert store.accept_answer(answer).acceptance == "accepted"
    view = research.task(receipt.task_id, actor.id)
    assert view.status == "researching"
    assert view.question is None
    assert (
        store.reserve_answer(
            actor.id,
            actor.generation,
            receipt.task_id,
            question.id,
            1,
            1,
            "answer-once",
            choices[1],
        ).id
        == answer.id
    )
    assert store.accept_answer(answer).acceptance == "accepted"
    assert research.task(receipt.task_id, actor.id).view_version == view.view_version

    with pytest.raises(ValueError, match="QUESTION_CLOSED"):
        store.reserve_answer(
            actor.id,
            actor.generation,
            receipt.task_id,
            question.id,
            1,
            1,
            "second-answer",
            choices[0],
        )


def test_competing_answers_only_one_changes_the_task(research_context):
    engine, research, (actor, _), plan = research_context
    choices = published_choices(engine)
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "question")
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    context = ResearchRunStore(engine).begin(receipt.task_id)
    store = ClarificationStore(engine)
    question = store.publish(
        context,
        1,
        ClarificationDraft("你指的是哪個版本？", choices),
        datetime.now(UTC) + timedelta(days=7),
    )
    first = store.reserve_answer(
        actor.id,
        actor.generation,
        receipt.task_id,
        question.id,
        1,
        1,
        "answer-12",
        choices[0],
    )
    second = store.reserve_answer(
        actor.id,
        actor.generation,
        receipt.task_id,
        question.id,
        1,
        1,
        "answer-15",
        choices[1],
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(store.accept_answer, (first, second)))
    assert sorted(result.acceptance for result in results) == ["accepted", "rejected"]
    assert {result.code for result in results} == {None, "QUESTION_CLOSED"}
    assert store.accept_answer(first).acceptance == results[0].acceptance
    assert store.accept_answer(second).acceptance == results[1].acceptance
    task = research.task(receipt.task_id, actor.id)
    assert task.status == "researching" and task.question is None


def test_question_deadline_fails_only_the_still_pending_task(research_context):
    engine, research, (actor, _), plan = research_context
    choices = published_choices(engine)
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "question")
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    context = ResearchRunStore(engine).begin(receipt.task_id)
    store = ClarificationStore(engine)
    expires_at = datetime.now(UTC) + timedelta(days=7)
    question = store.publish(
        context,
        1,
        ClarificationDraft("你指的是哪個版本？", choices),
        expires_at,
    )
    pending = store.reserve_answer(
        actor.id,
        actor.generation,
        receipt.task_id,
        question.id,
        question.waiting_version,
        1,
        "reply-at-deadline",
        choices[1],
    )
    assert pending.acceptance == "acceptance_pending"
    assert (
        store.expire(context, question.id, 1, expires_at - timedelta(seconds=1))
        is False
    )
    assert research.task(receipt.task_id, actor.id).status == "needs_input"
    assert store.expire(context, question.id, 1, expires_at) is True
    task = research.task(receipt.task_id, actor.id)
    assert task.status == "failed"
    assert task.error is not None and task.error.code == "INPUT_EXPIRED"
    assert task.question is None
    assert store.expire(context, question.id, 1, expires_at) is False
    rejected = store.reserve_answer(
        actor.id,
        actor.generation,
        receipt.task_id,
        question.id,
        question.waiting_version,
        1,
        "reply-at-deadline",
        choices[1],
    )
    assert rejected.id == pending.id
    assert rejected.acceptance == "rejected"
    assert rejected.code == "QUESTION_EXPIRED"
