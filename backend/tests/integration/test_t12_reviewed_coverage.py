from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from whisky.modules.catalog.publication import load_reviewed_release
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import CatalogReference, ResearchConditions
from whisky.modules.research.activities import ResearchActivities
from whisky.modules.research.contracts import ResearchRunContext
from whisky.modules.research.selection_v4 import (
    ExplorationIntent,
    FlavorContrast,
    select_research,
)

pytestmark = pytest.mark.integration


def snapshot_for(engine, budget):
    manifest = Path(__file__).parents[3] / "data/catalog/t12-expansion.reviewed.json"
    CatalogStore(engine).publish(load_reviewed_release(manifest.read_text()))
    conditions = ResearchConditions(
        entry="beginner", goal="找下一款", budget_twd=budget
    )
    context = ResearchRunContext(
        uuid4(), uuid4(), 1, 1, conditions, date(2026, 10, 1), "price-30d-v1", "v4"
    )
    return ResearchActivities(engine)._catalog_snapshot(context)


def test_reviewed_expansion_keeps_unqualified_prices_out_of_budget(research_context):
    snapshot = snapshot_for(research_context[0], Decimal(2500))
    eligible = {item.name for item in snapshot.items if item.eligible}
    assert len(snapshot.items) == 7
    assert {"格蘭昆奇 12 年", "格蘭菲迪 15 年 Solera"}.isdisjoint(eligible)
    assert {"麥卡倫雙桶 12 年", "拉弗格 10 年", "泰斯卡 10 年"} <= eligible


@pytest.mark.parametrize("budget,expected", [(Decimal(2500), False), (None, True)])
def test_floral_source_comparison_respects_price_policy(
    research_context, budget, expected
):
    snapshot = snapshot_for(research_context[0], budget)
    origin = next(item for item in snapshot.items if item.name == "麥卡倫雙桶 12 年")
    conditions = ResearchConditions(
        entry="existing_bottle",
        goal="比較香草與花香",
        budget_twd=budget,
        starting_bottle=CatalogReference(
            release_id=origin.release_id, item_id=origin.item_id
        ),
    )
    selection = select_research(
        conditions,
        snapshot,
        None,
        intent=ExplorationIntent(
            mode="contrast",
            contrast=FlavorContrast(
                origin_feature="香草",
                candidate_feature="花香",
            ),
        ),
    )
    names = {snapshot.items[index - 1].name for index in selection.candidate_indices}
    assert ("格蘭昆奇 12 年" in names) is expected
    if expected:
        assert all(comparison.difference for comparison in selection.comparisons)
    else:
        assert not names


def test_smoky_source_comparison_requires_both_reviewed_descriptions(research_context):
    snapshot = snapshot_for(research_context[0], Decimal(2500))
    origin = next(item for item in snapshot.items if item.name == "拉弗格 10 年")
    conditions = ResearchConditions(
        entry="existing_bottle",
        goal="比較海藻與胡椒",
        budget_twd=Decimal(2500),
        starting_bottle=CatalogReference(
            release_id=origin.release_id, item_id=origin.item_id
        ),
    )
    selection = select_research(
        conditions,
        snapshot,
        None,
        intent=ExplorationIntent(
            mode="contrast",
            contrast=FlavorContrast(
                origin_feature="海藻",
                candidate_feature="胡椒",
            ),
        ),
    )
    assert [
        snapshot.items[index - 1].name for index in selection.candidate_indices
    ] == ["泰斯卡 10 年"]
    difference = selection.comparisons[0].difference
    assert difference is not None
    assert all(
        claim.evidence_ids
        for claim in (*difference.origin_claims, *difference.candidate_claims)
    )
