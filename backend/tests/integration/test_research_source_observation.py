"""Unreviewed page observations are idempotent and fenced by the task owner."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_catalog_release import synthetic_release

from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.research.contracts import (
    ReadSourceRequest,
    ResearchSourceOption,
    SourceObservation,
)
from whisky.modules.research.report import ReportDraft
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.run_store import ResearchRunStore
from whisky.modules.research.source_observation import SourceObservationStore
from whisky.modules.research.store import ResearchConflict

pytestmark = pytest.mark.integration
TEST_SOURCE_URL = "https://www.drinks.com.tw/product.aspx?Id=1753"


def test_source_observation_retry_keeps_first_content_and_cancel_fences_late_write(
    research_context,
):
    engine, research, (actor, other), plan = research_context
    release = synthetic_release()
    release = replace(
        release, evidence=(replace(release.evidence[0], url=TEST_SOURCE_URL),)
    )
    CatalogStore(engine).publish(release)
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "observation")
    research.confirm(actor.id, actor.generation, receipt.id, f"run-{uuid4()}")
    context = ResearchRunStore(engine).begin(receipt.task_id)
    source = release.evidence[0]
    selected = ResearchSourceOption(
        1,
        1,
        release.id,
        release.items[0].bottle.version_id,
        source.id,
        source.publisher or "source",
    )
    request = ReadSourceRequest(context, selected)
    store = SourceObservationStore(engine)

    first = store.save(
        request,
        "activity-1",
        SourceObservation("ok", text="first", final_url=source.url),
    )
    repeated = store.save(
        request,
        "activity-1",
        SourceObservation("ok", text="later", final_url=source.url),
    )
    assert repeated == first
    with engine.connect() as connection:
        count = connection.scalar(
            text(
                "SELECT count(*) FROM research_source_observations WHERE task_id=:task"
            ),
            dict(task=receipt.task_id),
        )
    assert count == 1
    with pytest.raises(ResearchConflict, match="NOT_FOUND"):
        store.save(
            replace(request, context=replace(context, owner_id=other.id)),
            "activity-other",
            SourceObservation("ok", text="other", final_url=source.url),
        )
    with engine.begin() as connection:
        connection.execute(
            text("""
            UPDATE research_tasks SET status='cancelled',write_allowed=false
            WHERE id=:task
            """),
            dict(task=receipt.task_id),
        )
    with pytest.raises(ResearchConflict, match="TASK_NOT_WRITABLE"):
        store.save(
            request,
            "activity-late",
            SourceObservation("ok", text="late", final_url=source.url),
        )


def test_foreign_source_observation_cannot_be_linked_into_another_report(
    research_context,
):
    engine, research, (actor, other), plan = research_context
    release = synthetic_release()
    release = replace(
        release, evidence=(replace(release.evidence[0], url=TEST_SOURCE_URL),)
    )
    CatalogStore(engine).publish(release)
    own_receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "own-source")
    research.confirm(actor.id, actor.generation, own_receipt.id, f"run-{uuid4()}")
    context = ResearchRunStore(engine).begin(own_receipt.task_id)
    selected = ResearchSourceOption(
        1,
        1,
        release.id,
        release.items[0].bottle.version_id,
        release.evidence[0].id,
        "fixture",
    )
    observed = SourceObservationStore(engine).save(
        ReadSourceRequest(context, selected),
        "source",
        SourceObservation("ok", text="seen", final_url=release.evidence[0].url),
    )
    assert observed.id is not None
    other_plan = PlanStore(engine).create(
        other.id,
        other.generation,
        "other",
        ResearchConditions(entry="beginner", goal="獨立研究"),
    )
    other_receipt = research.reserve(
        other.id, other.generation, other_plan.id, 1, "other-source"
    )
    research.confirm(other.id, other.generation, other_receipt.id, f"run-{uuid4()}")

    with pytest.raises(ResearchConflict, match="INVALID_SOURCE_OBSERVATION"):
        ReportStore(engine).save(
            other.id,
            other.generation,
            other_receipt.task_id,
            "other-final",
            ReportDraft("其他帳號的研究", ()),
            policy_version="price-30d-v1",
            prompt_version="research-v3",
            model_version="fixture",
            source_observation_ids=(observed.id,),
        )
