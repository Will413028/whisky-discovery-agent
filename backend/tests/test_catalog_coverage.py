from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from whisky.modules.catalog.coverage import audit_catalog
from whisky.modules.catalog.publication import load_reviewed_release


def test_real_reviewed_sample_reports_missing_styles_and_unqualified_price():
    release = load_reviewed_release(
        (
            Path(__file__).parents[2] / "data/catalog/first-journey.reviewed.json"
        ).read_text()
    )
    report = audit_catalog(release, date(2026, 10, 1), Decimal(2500))
    assert report["missing_flavors"] == ["花香", "乾果", "煙燻"]
    assert len(report["price_gaps"]) == 1
    assert report["price_gaps"][0]["name"] == "格蘭菲迪 15 年 Solera"
    # A starting bottle is already owned; its price need not fit the new budget.
    assert len(report["paths"]) == 4
    assert all(
        path["shared_tags"] and path["candidate_tags"] for path in report["paths"]
    )


def sample():
    return load_reviewed_release(
        (
            Path(__file__).parents[2] / "data/catalog/first-journey.reviewed.json"
        ).read_text()
    )


def test_stale_prices_disable_budget_paths_but_allow_explicit_unbounded_exploration():
    release = sample()
    bounded = audit_catalog(release, date(2026, 11, 1), Decimal(2500))
    assert len(bounded["price_gaps"]) == 3
    assert bounded["paths"] == []
    assert len(bounded["missing_paths"]) == 3
    unbounded = audit_catalog(release, date(2026, 11, 1), None)
    assert len(unbounded["paths"]) == 6
    assert len(unbounded["price_gaps"]) == 3


def test_publication_guard_prevents_missing_evidence_from_becoming_coverage():
    release = sample()
    first = release.items[0]
    invalid = replace(
        first, facts=(replace(first.facts[0], evidence_ids=()), *first.facts[1:])
    )
    report = audit_catalog(
        replace(release, items=(invalid, *release.items[1:])), date(2026, 10, 1), None
    )
    assert report["publication_error"] == "Every fact and derived tag requires evidence"
    assert report["paths"] == []


def test_same_documented_flavor_does_not_fabricate_a_difference():
    release = sample()
    same = replace(
        release,
        items=tuple(
            replace(item, flavor_tags=item.flavor_tags[:1]) for item in release.items
        ),
    )
    report = audit_catalog(same, date(2026, 10, 1), None)
    assert report["paths"] == []
    assert len(report["missing_paths"]) == 3
