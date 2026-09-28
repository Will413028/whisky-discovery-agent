from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from test_catalog_release import synthetic_priced_release, synthetic_release

from whisky.modules.catalog.domain import taiwan_date
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.research.report import ReportCandidate, ReportClaim, ReportDraft
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.run_store import ResearchRunStore
from whisky.modules.research.store import ResearchConflict

pytestmark = pytest.mark.integration


def fact_claim(item, evidence_ids=None):
    fact = item.facts[0]
    return ReportClaim(
        "fact", fact.field, fact.value, evidence_ids or fact.evidence_ids
    )


def test_report_and_completed_task_commit_as_one_artifact(research_context):
    engine, research, (actor, _), plan = research_context
    release = synthetic_release()
    CatalogStore(engine).publish(release)
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "report")
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    draft = ReportDraft(
        summary="已查到來源支持的酒款",
        candidates=(
            ReportCandidate(
                release.id,
                release.items[0].id,
                (fact_claim(release.items[0]),),
                "官方來源說明版本與風味",
            ),
        ),
    )
    reports = ReportStore(engine)
    saved = reports.save(
        actor.id,
        actor.generation,
        receipt.task_id,
        "final-v1",
        draft,
        policy_version="price-30d-v1",
        prompt_version="research-v1",
        model_version="fixture-v1",
    )
    assert saved is not None
    assert saved.task_id == receipt.task_id
    view = research.task(receipt.task_id, actor.id)
    assert view.status == "completed"
    assert view.report_id == saved.id
    assert view.view_version == 3
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM research_reports")) == 1
        assert (
            connection.scalar(text("SELECT count(*) FROM research_report_claims")) == 1
        )

    recovered = reports.save(
        actor.id,
        actor.generation,
        receipt.task_id,
        "final-v1",
        replace(draft, summary="重試不改寫已保存結果"),
        policy_version="price-30d-v1",
        prompt_version="research-v1",
        model_version="fixture-v1",
    )
    assert recovered == saved
    assert research.task(receipt.task_id, actor.id).view_version == 3
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM research_reports")) == 1
        assert (
            connection.scalar(text("SELECT count(*) FROM research_report_claims")) == 1
        )


def test_interrupted_report_transaction_keeps_task_and_artifact_unmodified(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "report-fault")
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))

    def fail_after_insert(_conn, _cursor, statement, _params, _context, _many):
        if "SET status='completed'" in statement:
            raise RuntimeError("injected task update interruption")

    event.listen(engine, "before_cursor_execute", fail_after_insert)
    try:
        with pytest.raises(RuntimeError, match="task update interruption"):
            ReportStore(engine).save(
                actor.id,
                actor.generation,
                receipt.task_id,
                "final-v1",
                ReportDraft(summary="部分報告", candidates=()),
                policy_version="price-30d-v1",
                prompt_version="research-v1",
                model_version="fixture-v1",
            )
    finally:
        event.remove(engine, "before_cursor_execute", fail_after_insert)
    view = research.task(receipt.task_id, actor.id)
    assert view.status == "queued" and view.report_id is None
    assert view.view_version == 2
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM research_reports")) == 0


def test_empty_report_keeps_the_catalog_release_it_examined(research_context):
    engine, research, (actor, _), plan = research_context
    release = synthetic_release()
    CatalogStore(engine).publish(release)
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "empty-report")
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    saved = ReportStore(engine).save(
        actor.id,
        actor.generation,
        receipt.task_id,
        "final-v1",
        ReportDraft(summary="目前沒有符合條件的酒款", candidates=()),
        policy_version="price-30d-v1",
        prompt_version="research-v1",
        model_version="fixture-v1",
    )
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT catalog_release_id FROM research_reports WHERE id=:id"),
                {"id": saved.id},
            )
            == release.id
        )


def test_database_rejects_citation_for_a_different_report_candidate(research_context):
    engine, research, (actor, _), plan = research_context
    release = synthetic_release()
    first_item = release.items[0]
    other_evidence = replace(
        release.evidence[0],
        id=uuid4(),
        source_id=uuid4(),
        bottle_version_id=uuid4(),
    )
    other_item = replace(
        first_item,
        id=uuid4(),
        bottle=replace(first_item.bottle, version_id=other_evidence.bottle_version_id),
        facts=tuple(
            replace(fact, evidence_ids=(other_evidence.id,))
            for fact in first_item.facts
        ),
        flavor_tags=tuple(
            replace(tag, evidence_ids=(other_evidence.id,))
            for tag in first_item.flavor_tags
        ),
    )
    release = replace(
        release,
        items=(first_item, other_item),
        evidence=(*release.evidence, other_evidence),
    )
    CatalogStore(engine).publish(release)
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "citation-fk")
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    saved = ReportStore(engine).save(
        actor.id,
        actor.generation,
        receipt.task_id,
        "final-v1",
        ReportDraft(
            summary="候選一有來源",
            candidates=(
                ReportCandidate(
                    release.id, first_item.id, (fact_claim(first_item),), "來源一"
                ),
            ),
        ),
        policy_version="price-30d-v1",
        prompt_version="research-v1",
        model_version="fixture-v1",
    )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO research_report_citations
                    (report_id,ordinal,claim_ordinal,release_id,item_id,
                     bottle_version_id,kind,key,evidence_id)
                VALUES (:report,0,0,:release,:item,:bottle,'fact',:key,:evidence)
                """),
                dict(
                    report=saved.id,
                    release=release.id,
                    item=other_item.id,
                    bottle=other_item.bottle.version_id,
                    evidence=other_evidence.id,
                    key=other_item.facts[0].field,
                ),
            )


def test_candidate_must_cite_a_reviewed_source_fact(research_context):
    engine, research, (actor, _), plan = research_context
    release = synthetic_release()
    item = release.items[0]
    tag_evidence = replace(release.evidence[0], id=uuid4(), source_id=uuid4())
    tag = replace(item.flavor_tags[0], evidence_ids=(tag_evidence.id,))
    release = replace(
        release,
        items=(replace(item, flavor_tags=(tag,)),),
        evidence=(*release.evidence, tag_evidence),
    )
    CatalogStore(engine).publish(release)
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "tag-only")
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    with pytest.raises(ResearchConflict, match="INVALID_CANDIDATE"):
        ReportStore(engine).save(
            actor.id,
            actor.generation,
            receipt.task_id,
            "final-v1",
            ReportDraft(
                summary="只有整理標籤，沒有引用來源事實",
                candidates=(
                    ReportCandidate(
                        release.id,
                        item.id,
                        (ReportClaim("tag", tag.label, tag.label, (tag_evidence.id,)),),
                        "標籤不是來源事實",
                    ),
                ),
            ),
            policy_version="price-30d-v1",
            prompt_version="research-v1",
            model_version="fixture-v1",
        )


def test_final_candidate_cannot_bypass_strict_budget(research_context):
    engine, research, (actor, _), _ = research_context
    now = datetime.now(UTC)
    today = taiwan_date(now)
    release = synthetic_priced_release()
    evidence = replace(release.evidence[0], captured_at=now, checked_on=today)
    item = replace(release.items[0], reviewed_on=today)
    price = replace(
        release.prices[0],
        observation=replace(
            release.prices[0].observation, observed_at=now, checked_on=today
        ),
    )
    release = replace(
        release,
        published_at=now,
        evidence=(evidence,),
        items=(item,),
        prices=(price,),
    )
    CatalogStore(engine).publish(release)
    plan = PlanStore(engine).create(
        actor.id,
        actor.generation,
        "budget",
        ResearchConditions(
            entry="beginner", goal="預算內探索", budget_twd=Decimal("1500.49")
        ),
    )
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "strict-budget")
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    draft = ReportDraft(
        summary="候選價格超出上限",
        candidates=(
            ReportCandidate(
                release.id,
                item.id,
                (fact_claim(item),),
                "有來源，但價格不符合預算",
            ),
        ),
    )
    with pytest.raises(ResearchConflict, match="INVALID_CANDIDATE"):
        ReportStore(engine).save(
            actor.id,
            actor.generation,
            receipt.task_id,
            "final-v1",
            draft,
            policy_version="price-30d-v1",
            prompt_version="research-v1",
            model_version="fixture-v1",
        )
    assert research.task(receipt.task_id, actor.id).status == "queued"


def test_report_persists_selected_qualified_price_observation(research_context):
    engine, research, (actor, _), plan = research_context
    now = datetime.now(UTC)
    today = taiwan_date(now)
    release = synthetic_priced_release()
    evidence = replace(release.evidence[0], captured_at=now, checked_on=today)
    item = replace(release.items[0], reviewed_on=today)
    price = replace(
        release.prices[0],
        observation=replace(
            release.prices[0].observation, observed_at=now, checked_on=today
        ),
    )
    release = replace(
        release, published_at=now, evidence=(evidence,), items=(item,), prices=(price,)
    )
    CatalogStore(engine).publish(release)
    receipt = research.reserve(
        actor.id, actor.generation, plan.id, 1, "price-provenance"
    )
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    with pytest.raises(ResearchConflict, match="INVALID_CANDIDATE"):
        ReportStore(engine).save(
            actor.id,
            actor.generation,
            receipt.task_id,
            "final-v1",
            ReportDraft(
                summary="錯誤價格 ID",
                candidates=(
                    ReportCandidate(
                        release.id,
                        item.id,
                        (fact_claim(item),),
                        "已查核價",
                        (uuid4(),),
                    ),
                ),
            ),
            policy_version="price-30d-v1",
            prompt_version="research-v1",
            model_version="fixture-v1",
        )
    saved = ReportStore(engine).save(
        actor.id,
        actor.generation,
        receipt.task_id,
        "final-v1",
        ReportDraft(
            summary="有來源的價格觀察",
            candidates=(
                ReportCandidate(
                    release.id,
                    item.id,
                    (fact_claim(item),),
                    "已查核價",
                    (price.id,),
                ),
            ),
        ),
        policy_version="price-30d-v1",
        prompt_version="research-v1",
        model_version="fixture-v1",
    )
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT price_id FROM research_report_prices WHERE report_id=:id"),
                {"id": saved.id},
            )
            == price.id
        )
        assert (
            connection.scalar(
                text("SELECT evaluated_on FROM research_reports WHERE id=:id"),
                {"id": saved.id},
            )
            == today
        )
    snapshot = ReportStore(engine).read(actor.id, saved.id)
    assert snapshot is not None
    assert snapshot.candidates[0].prices[0].id == price.id
    assert snapshot.candidates[0].prices[0].source.url == evidence.url


def test_candidate_rejects_changed_claim_value(research_context):
    engine, research, (actor, _), plan = research_context
    release = synthetic_release()
    CatalogStore(engine).publish(release)
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "false-claim")
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    false_claim = replace(fact_claim(release.items[0]), value="模型捏造的值")
    with pytest.raises(ResearchConflict, match="INVALID_CANDIDATE"):
        ReportStore(engine).save(
            actor.id,
            actor.generation,
            receipt.task_id,
            "final-v1",
            ReportDraft(
                summary="不該保存",
                candidates=(
                    ReportCandidate(
                        release.id, release.items[0].id, (false_claim,), "理由"
                    ),
                ),
            ),
            policy_version="price-30d-v1",
            prompt_version="research-v1",
            model_version="fixture-v1",
        )


def test_report_rejects_policy_version_not_used_for_qualification(research_context):
    engine, research, (actor, _), plan = research_context
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "stale-policy")
    research.confirm(actor.id, actor.generation, receipt.id, str(uuid4()))
    with pytest.raises(ResearchConflict, match="POLICY_CHANGED"):
        ReportStore(engine).save(
            actor.id,
            actor.generation,
            receipt.task_id,
            "final-v1",
            ReportDraft(summary="不該保存", candidates=()),
            policy_version="price-29d-v1",
            prompt_version="research-v1",
            model_version="fixture-v1",
        )


def test_failure_projection_cannot_replace_completed_or_cancelled_task(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    run_store = ResearchRunStore(engine)
    completed = research.reserve(actor.id, actor.generation, plan.id, 1, "completed")
    research.confirm(actor.id, actor.generation, completed.id, str(uuid4()))
    completed_context = run_store.begin(completed.task_id)
    saved = ReportStore(engine).save(
        actor.id,
        actor.generation,
        completed.task_id,
        "final-v1",
        ReportDraft(summary="已完成", candidates=()),
        policy_version="price-30d-v1",
        prompt_version="research-v1",
        model_version="fixture-v1",
    )
    assert run_store.fail(completed_context) is False
    assert research.task(completed.task_id, actor.id).report_id == saved.id

    cancelled = research.reserve(actor.id, actor.generation, plan.id, 1, "cancelled")
    research.confirm(actor.id, actor.generation, cancelled.id, str(uuid4()))
    cancelled_context = run_store.begin(cancelled.task_id)
    with engine.begin() as connection:
        connection.execute(
            text("""
            UPDATE research_tasks SET status='cancelled',write_allowed=false
            WHERE id=:task
            """),
            {"task": cancelled.task_id},
        )
    assert run_store.fail(cancelled_context) is False
    assert research.task(cancelled.task_id, actor.id).status == "cancelled"
