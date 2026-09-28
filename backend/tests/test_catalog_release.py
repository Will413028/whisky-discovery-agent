from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from whisky.modules.catalog.domain import (
    Bottle,
    CatalogFact,
    CatalogItem,
    CatalogRelease,
    Evidence,
    FlavorTag,
    PriceObservation,
    PublishedPrice,
    validate_release,
)


def synthetic_release():
    bottle = Bottle(uuid4(), Decimal("46"), 700)
    evidence = Evidence(
        uuid4(),
        uuid4(),
        bottle.version_id,
        "https://synthetic.example/bottle",
        datetime(2026, 9, 28, tzinfo=UTC),
        date(2026, 9, 28),
        True,
        "Synthetic source publisher",
    )
    facts = tuple(
        CatalogFact(field, value, (evidence.id,))
        for field, value in [
            ("name", "Synthetic test bottle"),
            ("brand", "Synthetic brand"),
            ("official_name", "Synthetic test bottle"),
            ("market", "TW"),
            ("version_label", "Synthetic regular release"),
            ("abv", "46"),
            ("volume_ml", "700"),
        ]
    )
    item = CatalogItem(
        uuid4(),
        bottle,
        "Synthetic test bottle",
        facts,
        (
            FlavorTag(
                "synthetic-fruit", (evidence.id,), "editorial_source_summary", "1"
            ),
        ),
        True,
        date(2026, 9, 28),
    )
    return CatalogRelease(
        uuid4(), datetime(2026, 9, 28, tzinfo=UTC), (item,), (evidence,)
    )


def test_reviewed_release_with_resolvable_source_facts_is_publishable():
    validate_release(synthetic_release())


@pytest.mark.parametrize("missing", ["publisher", "method", "method_version"])
def test_new_publication_requires_publisher_and_versioned_flavor_method(missing):
    release = synthetic_release()
    if missing == "publisher":
        release = replace(
            release, evidence=(replace(release.evidence[0], publisher=None),)
        )
    else:
        item = release.items[0]
        tag = replace(item.flavor_tags[0], **{missing: None})
        release = replace(release, items=(replace(item, flavor_tags=(tag,)),))
    with pytest.raises(ValueError):
        validate_release(release)


@pytest.mark.parametrize("field", ["brand", "official_name", "market", "version_label"])
def test_new_release_requires_sourced_bottle_identity_fields(field):
    release = synthetic_release()
    item = release.items[0]
    incomplete = replace(
        item, facts=tuple(fact for fact in item.facts if fact.field != field)
    )
    with pytest.raises(ValueError):
        validate_release(replace(release, items=(incomplete,)))


@pytest.mark.parametrize("reviewed_on", [None, date(2027, 1, 1)])
def test_publication_requires_nonfuture_item_review_date(reviewed_on):
    release = synthetic_release()
    with pytest.raises(ValueError):
        validate_release(
            replace(
                release, items=(replace(release.items[0], reviewed_on=reviewed_on),)
            )
        )


def synthetic_priced_release():
    release = synthetic_release()
    evidence = release.evidence[0]
    price = PublishedPrice(
        uuid4(),
        release.items[0].id,
        evidence.id,
        PriceObservation(
            evidence.source_id,
            release.items[0].bottle,
            evidence.captured_at,
            evidence.checked_on,
            Decimal("1500.50"),
            True,
            "TW",
            "TWD",
            True,
        ),
    )
    return replace(release, prices=(price,))


@pytest.mark.parametrize(
    "fault", ["item", "evidence", "source", "bottle", "draft", "capture", "duplicate"]
)
def test_published_prices_require_unique_reviewed_same_source_bottle_references(fault):
    release = synthetic_priced_release()
    price = release.prices[0]
    if fault == "item":
        price = replace(price, item_id=uuid4())
    elif fault == "evidence":
        price = replace(price, evidence_id=uuid4())
    elif fault == "source":
        price = replace(
            price, observation=replace(price.observation, source_id=uuid4())
        )
    elif fault == "bottle":
        price = replace(
            price,
            observation=replace(
                price.observation,
                bottle=replace(price.observation.bottle, volume_ml=500),
            ),
        )
    elif fault == "draft":
        price = replace(price, observation=replace(price.observation, reviewed=False))
    elif fault == "capture":
        price = replace(
            price,
            observation=replace(
                price.observation, observed_at=datetime(2027, 1, 1, tzinfo=UTC)
            ),
        )
    prices = (price, price) if fault == "duplicate" else (price,)
    with pytest.raises(ValueError):
        validate_release(replace(release, prices=prices))


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com:invalid/source",
        "https://example.com:99999/source",
        "https://127.0.0.1/private",
        "https://localhost/private",
        "https://[::1]/private",
        "https://10.0.0.1/private",
    ],
)
def test_source_url_requires_valid_port_and_public_host(url):
    release = synthetic_release()
    with pytest.raises(ValueError):
        validate_release(
            replace(release, evidence=(replace(release.evidence[0], url=url),))
        )


def test_equivalent_abv_decimal_formats_do_not_create_source_conflicts():
    release = synthetic_release()
    item = release.items[0]
    validate_release(
        replace(
            release,
            items=(replace(item, bottle=replace(item.bottle, abv=Decimal("46.0"))),),
        )
    )


def test_draft_item_cannot_be_published_as_reviewed_catalog():
    release = synthetic_release()
    with pytest.raises(ValueError, match="reviewed"):
        validate_release(
            replace(release, items=(replace(release.items[0], reviewed=False),))
        )


@pytest.mark.parametrize("fault", ["missing", "draft", "other-bottle"])
def test_every_published_citation_resolves_to_reviewed_evidence_for_the_same_bottle(
    fault,
):
    release = synthetic_release()
    evidence = release.evidence[0]
    if fault == "missing":
        release = replace(release, evidence=())
    elif fault == "draft":
        release = replace(release, evidence=(replace(evidence, reviewed=False),))
    else:
        release = replace(
            release, evidence=(replace(evidence, bottle_version_id=uuid4()),)
        )
    with pytest.raises(ValueError, match="evidence"):
        validate_release(release)


@pytest.mark.parametrize(
    "fault",
    [
        "missing-facts",
        "empty-fact-citation",
        "empty-tag-citation",
        "wrong-name",
        "wrong-abv",
        "wrong-volume",
    ],
)
def test_publication_rejects_unsourced_or_contradictory_display_fields(fault):
    release = synthetic_release()
    item = release.items[0]
    if fault == "missing-facts":
        item = replace(item, facts=())
    elif fault == "empty-fact-citation":
        item = replace(
            item, facts=(replace(item.facts[0], evidence_ids=()), *item.facts[1:])
        )
    elif fault == "empty-tag-citation":
        item = replace(
            item, flavor_tags=(replace(item.flavor_tags[0], evidence_ids=()),)
        )
    else:
        field = {"wrong-name": "name", "wrong-abv": "abv", "wrong-volume": "volume_ml"}[
            fault
        ]
        item = replace(
            item,
            facts=tuple(
                replace(fact, value="999") if fact.field == field else fact
                for fact in item.facts
            ),
        )
    with pytest.raises(ValueError):
        validate_release(replace(release, items=(item,)))


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate-item",
        "duplicate-evidence",
        "duplicate-field",
        "bad-url",
        "future-check",
        "naive-capture",
        "future-capture",
        "naive-publication",
    ],
)
def test_release_identifiers_and_evidence_metadata_are_unambiguous(fault):
    release = synthetic_release()
    item, evidence = release.items[0], release.evidence[0]
    if fault == "duplicate-item":
        release = replace(release, items=(item, item))
    elif fault == "duplicate-evidence":
        release = replace(release, evidence=(evidence, evidence))
    elif fault == "duplicate-field":
        release = replace(
            release, items=(replace(item, facts=(*item.facts, item.facts[0])),)
        )
    elif fault == "naive-publication":
        release = replace(release, published_at=datetime(2026, 9, 28))
    else:
        changes = {
            "bad-url": {"url": "javascript:alert(1)"},
            "future-check": {"checked_on": date(2026, 9, 29)},
            "naive-capture": {"captured_at": datetime(2026, 9, 28)},
            "future-capture": {"captured_at": datetime(2026, 9, 29, tzinfo=UTC)},
        }[fault]
        release = replace(release, evidence=(replace(evidence, **changes),))
    with pytest.raises(ValueError):
        validate_release(release)
