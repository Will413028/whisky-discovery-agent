"""Reviewed catalog rules select eligible comparison candidates before model I/O."""

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
from whisky.modules.research.selection_v3 import select_research

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("goal", "budget", "selected_name", "expected", "version_names", "unlisted"),
    [
        (
            "喜歡格蘭菲迪 12 年的梨子果香，想找不同桶型、每瓶 2000 元內的選擇",
            "2000",
            None,
            ["格蘭利威 12 年"],
            [],
            None,
        ),
        ("找 800 元以內、帶果香的威士忌", "800", None, [], [], None),
        (
            "不確定喝的是格蘭菲迪 12 年還是 15 年 Solera，先確認版本",
            None,
            None,
            [],
            ["格蘭菲迪 12 年", "格蘭菲迪 15 年 Solera"],
            None,
        ),
        (
            "比較下一款的風味差異",
            None,
            "格蘭菲迪 12 年",
            ["格蘭菲迪 15 年 Solera", "格蘭利威 12 年"],
            [],
            None,
        ),
        (
            "查核格蘭利威 12 年雙橡木桶常規版的版本及台灣參考價",
            "1000",
            None,
            ["格蘭利威 12 年"],
            [],
            None,
        ),
        (
            "格蘭菲迪 15 年 Solera 在 1500 元內嗎？給我可用的候選",
            "1500",
            None,
            ["格蘭菲迪 12 年", "格蘭利威 12 年"],
            [],
            None,
        ),
        (
            "推薦 Ardbeg Ten 並比較煙燻程度",
            None,
            None,
            [],
            [],
            "Ardbeg Ten",
        ),
    ],
)
def test_frozen_journeys_use_rule_qualified_selection(
    research_context, goal, budget, selected_name, expected, version_names, unlisted
):
    engine, _, _, _ = research_context
    manifest = (
        Path(__file__).resolve().parents[3] / "data/catalog/first-journey.reviewed.json"
    ).read_text()
    CatalogStore(engine).publish(load_reviewed_release(manifest))
    conditions = ResearchConditions(
        entry="beginner",
        goal=goal,
        budget_twd=Decimal(budget) if budget is not None else None,
    )
    context = ResearchRunContext(
        uuid4(), uuid4(), 1, 1, conditions, date(2026, 9, 29), "price-30d-v1", "v3"
    )
    snapshot = ResearchActivities(engine)._catalog_snapshot(context)
    selected = next(
        (
            str(item.bottle_version_id)
            for item in snapshot.items
            if item.name == selected_name
        ),
        None,
    )
    decision = select_research(conditions, snapshot, selected)
    assert [
        snapshot.items[index - 1].name for index in decision.candidate_indices
    ] == expected
    assert [
        snapshot.items[index - 1].name for index in decision.version_indices
    ] == version_names
    assert decision.unlisted_name == unlisted


def test_structured_start_and_soft_preference_affect_new_bottle_order(research_context):
    engine, _, _, _ = research_context
    manifest = (
        Path(__file__).resolve().parents[3] / "data/catalog/first-journey.reviewed.json"
    ).read_text()
    CatalogStore(engine).publish(load_reviewed_release(manifest))
    base = ResearchConditions(entry="beginner", goal="想找下一款")
    context = ResearchRunContext(
        uuid4(), uuid4(), 1, 1, base, date(2026, 9, 29), "price-30d-v1", "v3"
    )
    snapshot = ResearchActivities(engine)._catalog_snapshot(context)
    starting = next(item for item in snapshot.items if item.name == "格蘭菲迪 12 年")
    conditions = ResearchConditions(
        entry="existing_bottle",
        goal="想找下一款",
        starting_bottle=CatalogReference(
            release_id=starting.release_id, item_id=starting.item_id
        ),
        preferences=(
            Preference(
                description="太妃糖",
                intent="prefer",
                certainty="user_stated",
                strength="soft",
            ),
        ),
    )
    selection = select_research(conditions, snapshot, None)
    assert [
        snapshot.items[index - 1].name for index in selection.candidate_indices
    ] == ["格蘭利威 12 年", "格蘭菲迪 15 年 Solera"]


def test_existing_bottle_entry_uses_reference_without_goal_keywords(research_context):
    engine, _, _, _ = research_context
    manifest = (
        Path(__file__).resolve().parents[3] / "data/catalog/first-journey.reviewed.json"
    ).read_text()
    CatalogStore(engine).publish(load_reviewed_release(manifest))
    base = ResearchConditions(entry="beginner", goal="想探索")
    context = ResearchRunContext(
        uuid4(), uuid4(), 1, 1, base, date(2026, 9, 29), "price-30d-v1", "v3"
    )
    snapshot = ResearchActivities(engine)._catalog_snapshot(context)
    starting = next(item for item in snapshot.items if item.name == "格蘭菲迪 12 年")
    reference = CatalogReference(
        release_id=starting.release_id, item_id=starting.item_id
    )
    conditions = ResearchConditions(
        entry="existing_bottle", goal="想探索", starting_bottle=reference
    )

    selected = select_research(conditions, snapshot, None)
    assert starting.index not in selected.candidate_indices

    conditions = conditions.model_copy(
        update={"goal": "不確定喝的是格蘭菲迪 12 年還是 15 年 Solera"}
    )
    selected = select_research(conditions, snapshot, None)
    assert selected.version_indices == ()


def test_explicit_hard_preference_requires_positive_reviewed_evidence(
    research_context,
):
    engine, _, _, _ = research_context
    manifest = (
        Path(__file__).resolve().parents[3] / "data/catalog/first-journey.reviewed.json"
    ).read_text()
    CatalogStore(engine).publish(load_reviewed_release(manifest))
    base = ResearchConditions(entry="beginner", goal="想找下一款")
    context = ResearchRunContext(
        uuid4(), uuid4(), 1, 1, base, date(2026, 9, 29), "price-30d-v1", "v3"
    )
    snapshot = ResearchActivities(engine)._catalog_snapshot(context)
    prefer_spice = ResearchConditions(
        entry="beginner",
        goal="想找下一款",
        preferences=(
            Preference(
                description="辛香",
                intent="prefer",
                certainty="user_stated",
                strength="hard",
            ),
        ),
    )
    selection = select_research(prefer_spice, snapshot, None)
    assert [
        snapshot.items[index - 1].name for index in selection.candidate_indices
    ] == ["格蘭菲迪 15 年 Solera"]
    avoid_smoke = ResearchConditions(
        entry="beginner",
        goal="想找下一款",
        preferences=(
            Preference(
                description="煙燻",
                intent="avoid",
                certainty="user_stated",
                strength="hard",
            ),
        ),
    )
    selection = select_research(avoid_smoke, snapshot, None)
    assert selection.candidate_indices == ()
    assert selection.unresolved
