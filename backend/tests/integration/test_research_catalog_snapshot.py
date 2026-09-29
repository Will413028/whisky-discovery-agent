"""A research decision must not combine two immutable catalog releases."""

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from test_catalog_release import synthetic_release

from whisky.modules.catalog import public as catalog_public
from whisky.modules.catalog.public import search_reviewed_candidates
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.research import activities
from whisky.modules.research.activities import ResearchActivities
from whisky.modules.research.contracts import ResearchRunContext

pytestmark = pytest.mark.integration


def test_catalog_publication_between_queries_cannot_disqualify_old_snapshot(
    research_context, monkeypatch
):
    engine, _, _, _ = research_context
    first = synthetic_release()
    second = replace(
        synthetic_release(), published_at=datetime(2026, 9, 29, tzinfo=UTC)
    )
    CatalogStore(engine).publish(first)
    reads = 0

    def publish_between_reads(engine, as_of, budget):
        nonlocal reads
        reads += 1
        if reads == 2:
            CatalogStore(engine).publish(second)
        return search_reviewed_candidates(engine, as_of, budget)

    monkeypatch.setattr(
        activities, "search_reviewed_candidates", publish_between_reads, raising=False
    )
    conditions = ResearchConditions(entry="beginner", goal="探索果香")
    context = ResearchRunContext(
        uuid4(), uuid4(), 1, 1, conditions, date(2026, 9, 29), "price-30d-v1", "v3"
    )
    snapshot = ResearchActivities(engine)._catalog_snapshot(context)
    assert len(snapshot.items) == 1
    assert snapshot.items[0].release_id == first.id
    assert snapshot.items[0].eligible
    assert all(source.release_id == first.id for source in snapshot.sources)


def test_public_snapshot_pins_release_when_publication_commits_mid_read(
    research_context, monkeypatch
):
    engine, _, _, _ = research_context
    first = synthetic_release()
    second = replace(
        synthetic_release(), published_at=datetime(2026, 9, 29, tzinfo=UTC)
    )
    CatalogStore(engine).publish(first)
    original = catalog_public.current_release_id
    published = False

    def publish_after_pin(connection):
        nonlocal published
        release_id = original(connection)
        if not published:
            published = True
            CatalogStore(engine).publish(second)
        return release_id

    monkeypatch.setattr(catalog_public, "current_release_id", publish_after_pin)
    snapshot = catalog_public.reviewed_catalog_snapshot(engine, date(2026, 9, 29), None)
    assert snapshot.release_id == first.id
    assert {item.release_id for item in snapshot.candidates} == {first.id}
    assert snapshot.eligible_item_ids == {first.items[0].id}
    assert {source.source.id for source in snapshot.sources} == {first.evidence[0].id}
