from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_comparison_reports_v4 import comparison_commit as comparison_commit
from test_library_conclusions import completed_choice as completed_choice

from whisky.modules.catalog.public import (
    current_release_id,
    reviewed_candidates_for_versions,
)
from whisky.modules.catalog.publication import load_reviewed_release
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.library.store import LibraryStore

pytestmark = pytest.mark.integration


def test_revisit_catalog_query_resolves_only_explicit_versions(completed_choice):
    engine, _, _, command = completed_choice
    with engine.connect() as connection:
        candidates = reviewed_candidates_for_versions(
            connection,
            current_release_id(connection),
            (command.selected_version_id,),
            date(2026, 9, 30),
        )
    assert len(candidates) == 1, (
        "catalog provides a bounded version resolution instead of a research snapshot"
    )
    assert candidates[0].item.bottle.version_id == command.selected_version_id


@pytest.mark.parametrize("as_of", [date(2026, 9, 30), date(2026, 11, 1)])
def test_revisit_resolves_current_prices_without_replacing_historical_choice(
    completed_choice, as_of
):
    engine, actor, _, command = completed_choice
    store = LibraryStore(engine)
    saved = store.save_conclusion(actor.id, actor.generation, command)
    current = store.revisit_conclusion(actor.id, saved.id, as_of)
    assert current is not None, "reopening must resolve current catalog and prices"
    assert current.conclusion_id == saved.id
    assert current.evaluated_on == as_of
    assert current.conditions_revision == saved.conditions_revision
    assert current.budget_twd == saved.conditions.budget_twd
    assert current.price_policy_version == "price-30d-v1"
    assert {item.bottle_version_id for item in current.items} == {
        saved.selected_version_id,
        *saved.alternative_version_ids,
    }
    for item in current.items:
        assert item.availability == "resolved"
        assert item.name
        if as_of == date(2026, 11, 1):
            assert item.price_upper_bound_twd is None
            assert item.price_qualification == "unqualified"
        assert item.budget_qualification == "not_filtered"
        if item.budget_qualification == "within_budget":
            assert item.price_upper_bound_twd is not None
            assert item.prices and all(
                price.checked_on <= as_of for price in item.prices
            )
    assert store.read_conclusion(actor.id, saved.id) == saved


def test_revisit_hides_private_history_from_foreign_and_deleted_owners(
    completed_choice,
):
    engine, actor, _, command = completed_choice
    store = LibraryStore(engine)
    saved = store.save_conclusion(actor.id, actor.generation, command)
    assert store.revisit_conclusion(uuid4(), saved.id, date(2026, 9, 30)) is None
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE plans SET deleted_at=now() WHERE id=:id"),
            {"id": saved.plan_id},
        )
    assert store.revisit_conclusion(actor.id, saved.id, date(2026, 9, 30)) is None


def test_new_release_removal_never_substitutes_a_different_bottle_version(
    completed_choice,
):
    engine, actor, _, command = completed_choice
    store = LibraryStore(engine)
    saved = store.save_conclusion(actor.id, actor.generation, command)
    manifest = Path(__file__).parents[3] / "data/catalog/first-journey.reviewed.json"
    release = load_reviewed_release(manifest.read_text())
    remaining = tuple(
        item
        for item in release.items
        if item.bottle.version_id != saved.selected_version_id
    )
    remaining_ids = {item.id for item in remaining}
    CatalogStore(engine).publish(
        replace(
            release,
            id=uuid4(),
            published_at=datetime(2026, 10, 1, tzinfo=UTC),
            items=remaining,
            prices=tuple(
                price for price in release.prices if price.item_id in remaining_ids
            ),
        )
    )
    current = store.revisit_conclusion(actor.id, saved.id, date(2026, 10, 1))
    assert (
        current is not None and current.catalog_release_id != saved.catalog_release_id
    )
    item = next(
        item
        for item in current.items
        if item.bottle_version_id == saved.selected_version_id
    )
    assert item.availability == "unresolved" and item.name is None
    assert item.prices == () and item.price_upper_bound_twd is None
    assert store.read_conclusion(actor.id, saved.id) == saved


@pytest.mark.parametrize(
    "budget,qualification", [("100", "over_budget"), ("10000", "within_budget")]
)
def test_current_budget_uses_saved_conditions_and_catalog_policy(
    completed_choice, budget, qualification
):
    engine, actor, report, command = completed_choice
    # Explicit synthetic conditions seed; production cannot rewrite captured tasks.
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE research_tasks SET conditions=jsonb_set(conditions,"
                "'{budget_twd}',CAST(:budget AS jsonb)) WHERE id=:id"
            ),
            {"budget": '"' + budget + '"', "id": report.task_id},
        )
    store = LibraryStore(engine)
    saved = store.save_conclusion(actor.id, actor.generation, command)
    current = store.revisit_conclusion(actor.id, saved.id, date(2026, 9, 30))
    assert current is not None
    priced = [item for item in current.items if item.price_upper_bound_twd is not None]
    assert priced and all(item.budget_qualification == qualification for item in priced)
    expired = store.revisit_conclusion(actor.id, saved.id, date(2026, 11, 1))
    assert expired is not None and all(
        item.budget_qualification == "unknown" for item in expired.items
    )
