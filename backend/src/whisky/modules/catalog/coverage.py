"""Offline reviewed-data coverage audit; no publishing or model calls."""

from datetime import date
from decimal import Decimal

from whisky.modules.catalog.domain import (
    CatalogRelease,
    fits_budget,
    price_upper_bound,
    taiwan_date,
    validate_release,
)

PRIORITY_FLAVORS = ("果香", "花香", "香草甜香", "乾果", "辛香", "煙燻")


def audit_catalog(
    release: CatalogRelease, as_of: date, budget: Decimal | None
) -> dict[str, object]:
    report: dict[str, object] = dict(
        release_id=str(release.id),
        evaluated_on=as_of.isoformat(),
        budget_twd=str(budget) if budget is not None else None,
        missing_flavors=[],
        price_gaps=[],
        paths=[],
        missing_paths=[],
        publication_error=None,
        interpretation=(
            "Source-described tags do not establish absent flavors or intensity."
        ),
    )
    try:
        validate_release(release)
        if as_of < taiwan_date(release.published_at):
            raise ValueError("Catalog was not yet published on the evaluation date")
    except ValueError as error:
        report["publication_error"] = str(error)
        return report
    tags = {item.id: {tag.label for tag in item.flavor_tags} for item in release.items}
    covered = set().union(*tags.values())
    report["missing_flavors"] = [tag for tag in PRIORITY_FLAVORS if tag not in covered]
    gaps: list[dict[str, str]] = []
    eligible = set()
    for item in release.items:
        upper = price_upper_bound(
            item.bottle,
            [price.observation for price in release.prices if price.item_id == item.id],
            as_of,
        )
        if upper is None:
            gaps.append(
                dict(item_id=str(item.id), name=item.name, code="NO_QUALIFIED_PRICE")
            )
        if fits_budget(upper, budget):
            eligible.add(item.id)
    paths: list[dict[str, object]] = []
    missing: list[dict[str, str]] = []
    for starting in release.items:
        found = False
        for candidate in release.items:
            if candidate.id == starting.id or candidate.id not in eligible:
                continue
            shared = tags[starting.id] & tags[candidate.id]
            documented = tags[candidate.id] - tags[starting.id]
            if shared and documented:
                found = True
                paths.append(
                    dict(
                        starting_item_id=str(starting.id),
                        candidate_item_id=str(candidate.id),
                        shared_tags=sorted(shared),
                        candidate_tags=sorted(documented),
                    )
                )
        if not found:
            missing.append(dict(item_id=str(starting.id), name=starting.name))
    report.update(price_gaps=gaps, paths=paths, missing_paths=missing)
    return report
