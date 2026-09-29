"""V3 clarification payload contains reviewed version IDs, not draft prose."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from test_catalog_release import synthetic_versioned_release

from whisky.modules.catalog.store import CatalogStore
from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.run_store import ResearchRunStore
from whisky.modules.research.store import ResearchConflict

pytestmark = pytest.mark.integration


def test_v3_question_is_canonical_and_idempotent_from_version_ids(research_context):
    engine, research, (actor, _), plan = research_context
    release = synthetic_versioned_release()
    CatalogStore(engine).publish(release)
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "version-ids")
    research.confirm(actor.id, actor.generation, receipt.id, f"run-{uuid4()}")
    context = ResearchRunStore(engine).begin(receipt.task_id)
    versions = tuple(item.bottle.version_id for item in release.items)
    expires_at = datetime.now(UTC) + timedelta(days=7)
    store = ClarificationStore(engine)

    first = store.publish_reviewed_versions(
        context, 1, versions, expires_at, release.id
    )
    second = store.publish_reviewed_versions(
        context, 1, versions, expires_at, release.id
    )

    assert second.id == first.id
    question = research.task(receipt.task_id, actor.id).question
    assert question is not None
    assert all(item.name in question.prompt for item in release.items)
    assert [choice.id for choice in question.choices] == list(versions)


def test_v3_question_refuses_release_drift_even_when_version_ids_survive(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    release = synthetic_versioned_release()
    catalog = CatalogStore(engine)
    catalog.publish(release)
    receipt = research.reserve(actor.id, actor.generation, plan.id, 1, "drift")
    research.confirm(actor.id, actor.generation, receipt.id, f"run-{uuid4()}")
    context = ResearchRunStore(engine).begin(receipt.task_id)
    versions = tuple(item.bottle.version_id for item in release.items)
    catalog.publish(
        replace(
            release, id=uuid4(), published_at=release.published_at + timedelta(days=1)
        )
    )

    with pytest.raises(ResearchConflict, match="CATALOG_CHANGED"):
        ClarificationStore(engine).publish_reviewed_versions(
            context, 1, versions, datetime.now(UTC) + timedelta(days=7), release.id
        )
