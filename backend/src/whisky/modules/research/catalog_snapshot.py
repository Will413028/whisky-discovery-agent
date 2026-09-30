"""Convert the catalog's public pinned snapshot into research evidence."""

from whisky.modules.catalog.public import ReviewedCatalogSnapshot
from whisky.modules.research.contracts import (
    ResearchCatalogItem,
    ResearchCatalogSnapshot,
    ResearchSourceOption,
)
from whisky.modules.research.report import ReportClaim


def research_catalog_snapshot(
    catalog: ReviewedCatalogSnapshot,
) -> ResearchCatalogSnapshot:
    items: list[ResearchCatalogItem] = []
    sources: list[ResearchSourceOption] = []
    for index, candidate in enumerate(catalog.candidates, start=1):
        item = candidate.item
        eligible = item.id in catalog.eligible_item_ids
        facts = {fact.field: fact.value for fact in item.facts}
        claims = tuple(
            ReportClaim("fact", fact.field, fact.value, fact.evidence_ids)
            for fact in item.facts
        ) + tuple(
            ReportClaim("tag", tag.label, tag.label, tag.evidence_ids)
            for tag in item.flavor_tags
        )
        items.append(
            ResearchCatalogItem(
                index=index,
                release_id=candidate.release_id,
                item_id=item.id,
                bottle_version_id=item.bottle.version_id,
                name=item.name,
                official_name=facts.get("official_name", ""),
                version_label=facts.get("version_label", ""),
                tasting_notes=facts.get("producer_tasting_notes", ""),
                flavor_tags=tuple(tag.label for tag in item.flavor_tags),
                eligible=eligible,
                price_upper_bound_twd=(
                    str(candidate.price_upper_bound)
                    if candidate.price_upper_bound is not None
                    else None
                ),
                price_ids=tuple(price.id for price in candidate.prices)
                if eligible
                else (),
                claims=claims,
            )
        )
        for reviewed_source in catalog.sources:
            if reviewed_source.item_id != item.id:
                continue
            sources.append(
                ResearchSourceOption(
                    index=len(sources) + 1,
                    item_index=index,
                    release_id=candidate.release_id,
                    bottle_version_id=item.bottle.version_id,
                    evidence_id=reviewed_source.source.id,
                    publisher=reviewed_source.source.publisher or "來源未標示",
                )
            )
    return ResearchCatalogSnapshot(catalog.release_id, tuple(items), tuple(sources))
