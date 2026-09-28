import json
from dataclasses import asdict
from pathlib import Path

import pytest
from test_catalog_release import synthetic_priced_release

from whisky.modules.catalog.publication import load_reviewed_release


def reviewed_fixture_payload():
    release = synthetic_priced_release()
    return release, json.dumps(
        {
            "schema_version": 1,
            "data_kind": "real",
            "review_status": "reviewed",
            "reviewed_by": "Synthetic test reviewer",
            "reviewed_at": release.published_at.isoformat(),
            "release": asdict(release),
        },
        default=str,
    )


def test_explicit_reviewed_manifest_loads_typed_release_with_exact_prices():
    release, payload = reviewed_fixture_payload()
    assert load_reviewed_release(payload) == release


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("data_kind", "synthetic"),
        ("review_status", "draft"),
        ("reviewed_by", None),
        ("reviewed_by", " "),
        ("reviewed_at", None),
        ("reviewed_at", "2026-09-28T00:00:00"),
        ("reviewed_at", "2027-01-01T00:00:00Z"),
    ],
)
def test_manifest_requires_real_reviewed_version_with_attributed_aware_review(
    field, value
):
    _, payload = reviewed_fixture_payload()
    document = json.loads(payload)
    document[field] = value
    with pytest.raises(ValueError):
        load_reviewed_release(json.dumps(document))


def test_a_reviewed_envelope_cannot_promote_draft_items():
    _, payload = reviewed_fixture_payload()
    document = json.loads(payload)
    document["release"]["items"][0]["reviewed"] = False
    with pytest.raises(ValueError):
        load_reviewed_release(json.dumps(document))


def test_checked_in_real_draft_is_not_publishable():
    path = Path(__file__).parents[2] / "data/catalog/first-journey.draft.json"
    with pytest.raises(ValueError):
        load_reviewed_release(path.read_text())


@pytest.mark.parametrize("field", ["market", "currency", "unconditional"])
def test_manifest_must_not_infer_missing_price_qualification_metadata(field):
    _, payload = reviewed_fixture_payload()
    document = json.loads(payload)
    del document["release"]["prices"][0]["observation"][field]
    with pytest.raises(ValueError):
        load_reviewed_release(json.dumps(document))


@pytest.mark.parametrize("checked_on", ["2027-01-01", "2026-09-29", "2026-09-27"])
def test_price_check_date_cannot_disagree_with_its_source_evidence(checked_on):
    _, payload = reviewed_fixture_payload()
    document = json.loads(payload)
    document["release"]["prices"][0]["observation"]["checked_on"] = checked_on
    with pytest.raises(ValueError):
        load_reviewed_release(json.dumps(document))
