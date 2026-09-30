from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from whisky.modules.catalog.publication import load_reviewed_release
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import (
    CatalogReference,
    Preference,
    ResearchConditions,
)
from whisky.modules.research.activities import ResearchActivities
from whisky.modules.research.contracts import ResearchRunContext
from whisky.modules.research.selection_v4 import (
    ExplorationIntent,
    FlavorContrast,
    select_research,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def snapshot(research_context):
    engine, _, _, _ = research_context
    manifest = (
        Path(__file__).resolve().parents[3] / "data/catalog/first-journey.reviewed.json"
    )
    CatalogStore(engine).publish(load_reviewed_release(manifest.read_text()))
    conditions = ResearchConditions(
        entry="beginner", goal="找下一款", budget_twd=Decimal("1000")
    )
    context = ResearchRunContext(
        uuid4(), uuid4(), 1, 1, conditions, date(2026, 9, 30), "price-30d-v1", "v4"
    )
    return ResearchActivities(engine)._catalog_snapshot(context)


@pytest.mark.parametrize("query", ["格蘭菲迪", "格蘭菲迪 12 年"])
def test_unconfirmed_origin_requires_version_selection(snapshot, query):
    conditions = ResearchConditions(entry="beginner", goal="想找下一款")
    result = select_research(
        conditions, snapshot, None, intent=ExplorationIntent(origin_query=query)
    )
    assert result.candidate_indices == ()
    assert result.version_indices
    names = [snapshot.items[index - 1].name for index in result.version_indices]
    assert names == (
        ["格蘭菲迪 12 年", "格蘭菲迪 15 年 Solera"]
        if "12 年" not in query
        else ["格蘭菲迪 12 年"]
    )


def test_selected_version_must_belong_to_snapshot(snapshot):
    result = select_research(
        ResearchConditions(entry="beginner", goal="喜歡格蘭菲迪，找下一款"),
        snapshot,
        str(uuid4()),
    )
    assert result.candidate_indices == ()
    assert result.unresolved


def test_confirmed_start_is_excluded_without_filling_three_slots(snapshot):
    start = next(item for item in snapshot.items if item.name == "格蘭菲迪 12 年")
    conditions = ResearchConditions(
        entry="existing_bottle",
        goal="保留果香，找下一款",
        starting_bottle=CatalogReference(
            release_id=start.release_id, item_id=start.item_id
        ),
        budget_twd=Decimal("1000"),
    )
    result = select_research(conditions, snapshot, None)
    assert [snapshot.items[index - 1].name for index in result.candidate_indices] == [
        "格蘭利威 12 年"
    ]


def test_unlisted_liked_origin_is_not_replaced_by_catalog_bottle(snapshot):
    result = select_research(
        ResearchConditions(
            entry="beginner", goal="喜歡 Ardbeg Ten，想找少一點煙燻的下一款"
        ),
        snapshot,
        None,
        intent=ExplorationIntent(origin_query="Ardbeg Ten"),
    )
    assert result.candidate_indices == ()
    assert result.unlisted_name == "Ardbeg Ten"


def test_soft_direction_without_scale_stays_unresolved(snapshot):
    start = snapshot.items[0]
    conditions = ResearchConditions(
        entry="existing_bottle",
        goal="保留果香，少一點煙燻",
        starting_bottle=CatalogReference(
            release_id=start.release_id, item_id=start.item_id
        ),
    )
    result = select_research(
        conditions, snapshot, None, intent=ExplorationIntent(smoke_comparison=True)
    )
    assert any("煙燻" in text and "比較" in text for text in result.unresolved)


def test_official_english_brand_also_requires_confirmed_version(snapshot):
    result = select_research(
        ResearchConditions(
            entry="beginner", goal="I like Glenfiddich and want another bottle"
        ),
        snapshot,
        None,
        intent=ExplorationIntent(origin_query="Glenfiddich"),
    )
    assert result.candidate_indices == ()
    assert result.version_indices == (1, 2)


@pytest.mark.parametrize(
    "label,intent", [("煙燻", "avoid"), ("少煙燻", "change"), ("未收錄風味", "keep")]
)
def test_unsupported_hard_requirement_has_no_candidates(snapshot, label, intent):
    conditions = ResearchConditions(
        entry="beginner",
        goal="找下一款",
        preferences=(
            Preference(
                description=label,
                intent=intent,
                certainty="user_stated",
                strength="hard",
            ),
        ),
    )
    result = select_research(conditions, snapshot, None)
    assert result.candidate_indices == ()
    assert result.unresolved


def test_inferred_food_clue_does_not_rank_as_confirmed_preference(snapshot):
    conditions = ResearchConditions(
        entry="beginner",
        goal="看看選擇",
        preferences=(
            Preference(
                description="太妃糖",
                intent="prefer",
                certainty="inferred",
                strength="soft",
            ),
        ),
    )
    result = select_research(conditions, snapshot, None)
    assert result.candidate_indices == (1, 3)


def test_answer_cannot_silently_replace_structured_origin(snapshot):
    start = snapshot.items[0]
    conditions = ResearchConditions(
        entry="existing_bottle",
        goal="找下一款",
        starting_bottle=CatalogReference(
            release_id=start.release_id, item_id=start.item_id
        ),
    )
    result = select_research(
        conditions, snapshot, str(snapshot.items[-1].bottle_version_id)
    )
    assert result.candidate_indices == ()
    assert result.unresolved


def test_typed_origin_search_does_not_depend_on_goal_wording(snapshot):
    result = select_research(
        ResearchConditions(entry="beginner", goal="新的探索"),
        snapshot,
        None,
        intent=ExplorationIntent(origin_query="格蘭菲迪"),
    )
    assert result.version_indices == (1, 2)
    assert result.candidate_indices == ()


def test_similar_strategy_returns_positive_common_evidence(snapshot):
    start = snapshot.items[0]
    conditions = ResearchConditions(
        entry="existing_bottle",
        goal="新的探索",
        starting_bottle=CatalogReference(
            release_id=start.release_id, item_id=start.item_id
        ),
    )
    result = select_research(
        conditions, snapshot, None, intent=ExplorationIntent(mode="similar")
    )
    assert result.comparisons
    assert all(
        comparison.mode == "similar" and comparison.common_tags
        for comparison in result.comparisons
    )
    assert all(
        comparison.origin_claims and comparison.candidate_claims
        for comparison in result.comparisons
    )


def test_small_step_requires_retained_feature_and_cited_direction(snapshot):
    start = snapshot.items[0]
    conditions = ResearchConditions(
        entry="existing_bottle",
        goal="新的探索",
        starting_bottle=CatalogReference(
            release_id=start.release_id, item_id=start.item_id
        ),
        preferences=(
            Preference(
                description="果香",
                intent="keep",
                certainty="user_stated",
                strength="soft",
            ),
        ),
    )
    result = select_research(
        conditions,
        snapshot,
        None,
        intent=ExplorationIntent(mode="small_step", explore_feature="太妃糖"),
    )
    assert result.candidate_indices == (3,)
    assert result.comparisons[0].explore_claims
    assert all(
        claim.evidence_ids and "太妃糖" in claim.value
        for claim in result.comparisons[0].explore_claims
    )


def test_unproved_exploration_direction_is_not_replaced_with_arbitrary_choice(snapshot):
    result = select_research(
        ResearchConditions(entry="beginner", goal="新的探索"),
        snapshot,
        None,
        intent=ExplorationIntent(mode="small_step", explore_feature="未知特徵"),
    )
    assert result.candidate_indices == ()
    assert result.unresolved


def test_small_step_cannot_claim_retention_without_origin_evidence(snapshot):
    start = snapshot.items[0]
    missing = replace(
        start, claims=tuple(claim for claim in start.claims if claim.key != "果香")
    )
    incomplete = replace(snapshot, items=(missing, *snapshot.items[1:]))
    conditions = ResearchConditions(
        entry="existing_bottle",
        goal="新的探索",
        starting_bottle=CatalogReference(
            release_id=start.release_id, item_id=start.item_id
        ),
        preferences=(
            Preference(
                description="果香",
                intent="keep",
                certainty="user_stated",
                strength="soft",
            ),
        ),
    )
    result = select_research(
        conditions,
        incomplete,
        None,
        intent=ExplorationIntent(mode="small_step", explore_feature="太妃糖"),
    )
    assert result.candidate_indices == ()
    assert result.unresolved


def test_different_notes_alone_do_not_prove_contrast(snapshot):
    start = snapshot.items[0]
    conditions = ResearchConditions(
        entry="existing_bottle",
        goal="新的探索",
        starting_bottle=CatalogReference(
            release_id=start.release_id, item_id=start.item_id
        ),
    )
    result = select_research(
        conditions, snapshot, None, intent=ExplorationIntent(mode="contrast")
    )
    assert result.candidate_indices == ()
    assert result.unresolved


def test_contrast_identifies_axis_and_two_positive_sourced_descriptors(snapshot):
    start = snapshot.items[0]
    conditions = ResearchConditions(
        entry="existing_bottle",
        goal="新的探索",
        starting_bottle=CatalogReference(
            release_id=start.release_id, item_id=start.item_id
        ),
    )
    result = select_research(
        conditions,
        snapshot,
        None,
        intent=ExplorationIntent(
            mode="contrast",
            contrast=FlavorContrast(
                origin_feature="奶油糖", candidate_feature="太妃糖"
            ),
        ),
    )
    assert result.candidate_indices == (3,)
    difference = result.comparisons[0].difference
    assert difference is not None
    assert difference.axis == "flavor_description"
    assert difference.origin_feature == "奶油糖"
    assert difference.candidate_feature == "太妃糖"
    assert all(
        claim.evidence_ids and "奶油糖" in claim.value
        for claim in difference.origin_claims
    )
    assert all(
        claim.evidence_ids and "太妃糖" in claim.value
        for claim in difference.candidate_claims
    )
