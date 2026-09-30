"""Catalog queries available to other business modules."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection, Engine, text

from whisky.modules.catalog.domain import (
    Bottle,
    CatalogCandidate,
    PriceObservation,
    PricePolicy,
    PublishedPrice,
    fits_budget,
    qualified_prices,
)
from whisky.modules.catalog.domain import (
    taiwan_date as taiwan_date,
)


def search_reviewed_candidates(
    engine: Engine, as_of: date, budget: Decimal | None
) -> tuple[CatalogCandidate, ...]:
    """Expose reviewed search without sharing catalog storage internals."""
    from whisky.modules.catalog.store import CatalogStore

    return CatalogStore(engine).candidates(as_of, budget)


def price_policy_version() -> str:
    """Name the active qualification window in the same place as its rule."""
    return f"price-{PricePolicy().maximum_age_days}d-v1"


@dataclass(frozen=True)
class VerifiedReportCandidate:
    bottle_version_id: UUID
    price_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class PublishedSource:
    id: UUID
    url: str
    publisher: str | None
    checked_on: date


@dataclass(frozen=True)
class ReviewedCatalogSource:
    item_id: UUID
    bottle_version_id: UUID
    source: PublishedSource


@dataclass(frozen=True)
class ReviewedCatalogSnapshot:
    release_id: UUID | None
    candidates: tuple[CatalogCandidate, ...]
    eligible_item_ids: frozenset[UUID]
    sources: tuple[ReviewedCatalogSource, ...]


def reviewed_catalog_snapshot(
    engine: Engine, as_of: date, budget: Decimal | None
) -> ReviewedCatalogSnapshot:
    """Pin one immutable sealed release for eligibility and source selection."""

    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        release_id = current_release_id(connection)
        return reviewed_catalog_snapshot_in_release(
            connection, release_id, as_of, budget
        )


def reviewed_catalog_snapshot_in_release(
    connection: Connection,
    release_id: UUID | None,
    as_of: date,
    budget: Decimal | None,
) -> ReviewedCatalogSnapshot:
    """Read a pinned release inside the caller's artifact transaction."""
    from whisky.modules.catalog.store import CatalogStore

    candidates = CatalogStore.candidates_in_release(connection, release_id, as_of, None)
    eligible_ids = frozenset(
        candidate.item.id
        for candidate in candidates
        if fits_budget(candidate.price_upper_bound, budget)
    )
    sources = []
    if release_id is not None:
        for candidate in candidates:
            item = candidate.item
            evidence_ids = sorted(
                {
                    evidence_id
                    for fact in item.facts
                    for evidence_id in fact.evidence_ids
                }
                | {
                    evidence_id
                    for tag in item.flavor_tags
                    for evidence_id in tag.evidence_ids
                },
                key=str,
            )
            for evidence_id in evidence_ids:
                source = published_source(
                    connection, release_id, evidence_id, item.bottle.version_id
                )
                if source is not None:
                    sources.append(
                        ReviewedCatalogSource(item.id, item.bottle.version_id, source)
                    )
    return ReviewedCatalogSnapshot(release_id, candidates, eligible_ids, tuple(sources))


@dataclass(frozen=True)
class PublishedPriceDetail:
    id: UUID
    amount: Decimal | None
    currency: str
    market: str
    volume_ml: int | None
    checked_on: date | None
    source: PublishedSource


@dataclass(frozen=True)
class ReviewedVersion:
    release_id: UUID
    item_id: UUID
    bottle_version_id: UUID
    name: str


def reviewed_version_in_release(
    connection: Connection, release_id: UUID, bottle_version_id: UUID
) -> ReviewedVersion | None:
    """Resolve a stable bottle version in a specific sealed reviewed release."""
    row = connection.execute(
        text("""
        SELECT i.id,i.name FROM catalog_items i
        JOIN catalog_releases r ON r.id=i.release_id
        WHERE i.release_id=:release AND i.bottle_version_id=:bottle
          AND i.reviewed AND r.sealed
        """),
        dict(release=release_id, bottle=bottle_version_id),
    ).first()
    return (
        ReviewedVersion(release_id, row.id, bottle_version_id, row.name)
        if row
        else None
    )


def published_item_name(
    connection: Connection, release_id: UUID, item_id: UUID, bottle_version_id: UUID
) -> str | None:
    """Resolve a report's immutable reviewed bottle reference."""
    return connection.scalar(
        text("""
        SELECT i.name FROM catalog_items i
        JOIN catalog_releases r ON r.id=i.release_id
        WHERE i.release_id=:release AND i.id=:item
          AND i.bottle_version_id=:bottle AND i.reviewed AND r.sealed
        """),
        dict(release=release_id, item=item_id, bottle=bottle_version_id),
    )


def published_source(
    connection: Connection, release_id: UUID, evidence_id: UUID, bottle_version_id: UUID
) -> PublishedSource | None:
    """Resolve a source against the sealed historical release."""
    row = connection.execute(
        text("""
        SELECT e.id,e.url,e.publisher,e.checked_on FROM catalog_evidence e
        JOIN catalog_releases r ON r.id=e.release_id
        WHERE e.release_id=:release AND e.id=:evidence
          AND e.bottle_version_id=:bottle AND e.reviewed AND r.sealed
        """),
        dict(release=release_id, evidence=evidence_id, bottle=bottle_version_id),
    ).first()
    return PublishedSource(*row) if row else None


def published_price_detail(
    connection: Connection,
    release_id: UUID,
    item_id: UUID,
    bottle_version_id: UUID,
    price_id: UUID,
) -> PublishedPriceDetail | None:
    """Resolve price and source without applying today's qualification policy."""
    row = (
        connection.execute(
            text("""
        SELECT p.id,p.amount,p.currency,p.market,p.checked_on,
               i.volume_ml,e.id AS evidence_id,e.url,e.publisher,
               e.checked_on AS source_checked_on
        FROM catalog_prices p
        JOIN catalog_items i
          ON (i.release_id,i.id,i.bottle_version_id)=
             (p.release_id,p.item_id,p.bottle_version_id)
        JOIN catalog_evidence e
          ON (e.release_id,e.id,e.bottle_version_id)=
             (p.release_id,p.evidence_id,p.bottle_version_id)
        JOIN catalog_releases r ON r.id=p.release_id
        WHERE p.release_id=:release AND p.id=:price AND p.item_id=:item
          AND p.bottle_version_id=:bottle AND r.sealed
        """),
            dict(
                release=release_id,
                price=price_id,
                item=item_id,
                bottle=bottle_version_id,
            ),
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return PublishedPriceDetail(
        row["id"],
        row["amount"],
        row["currency"],
        row["market"],
        row["volume_ml"],
        row["checked_on"],
        PublishedSource(
            row["evidence_id"], row["url"], row["publisher"], row["source_checked_on"]
        ),
    )


def current_release_id(connection: Connection) -> UUID | None:
    """Return the latest sealed catalog version visible to this transaction."""
    return connection.scalar(
        text("""SELECT id FROM catalog_releases
        WHERE sealed ORDER BY published_at DESC LIMIT 1""")
    )


def is_published_item(connection: Connection, release_id: UUID, item_id: UUID) -> bool:
    return bool(
        connection.scalar(
            text("""
        SELECT EXISTS (
            SELECT 1 FROM catalog_items i
            JOIN catalog_releases r ON r.id = i.release_id
            WHERE i.release_id = :release AND i.id = :item AND i.reviewed AND r.sealed
        )
    """),
            dict(release=release_id, item=item_id),
        )
    )


def reviewed_citation_bottle(
    connection: Connection,
    release_id: UUID,
    item_id: UUID,
    claims: tuple[tuple[str, str, str, tuple[UUID, ...]], ...],
) -> UUID | None:
    """Require exact claim values and their reviewed same-bottle citations."""
    if not claims or len({(kind, key) for kind, key, _, _ in claims}) != len(claims):
        return None
    row = connection.execute(
        text("""
        SELECT i.bottle_version_id FROM catalog_items i
        JOIN catalog_releases r ON r.id=i.release_id
        WHERE i.release_id=:release AND i.id=:item AND i.reviewed AND r.sealed
        """),
        dict(release=release_id, item=item_id),
    ).first()
    if row is None:
        return None
    if not any(kind == "fact" for kind, _, _, _ in claims):
        return None
    for kind, key, value, evidence_ids in claims:
        if (
            kind not in {"fact", "tag"}
            or not key.strip()
            or not value.strip()
            or not evidence_ids
            or len(set(evidence_ids)) != len(evidence_ids)
        ):
            return None
        verified = connection.execute(
            text("""
            SELECT c.value,cc.evidence_id FROM catalog_claims c
            JOIN catalog_citations cc
              ON (cc.release_id,cc.item_id,cc.kind,cc.key)=
                 (c.release_id,c.item_id,c.kind,c.key)
            JOIN catalog_evidence e
              ON (e.release_id,e.id,e.bottle_version_id)=
                 (cc.release_id,cc.evidence_id,cc.bottle_version_id)
            WHERE c.release_id=:release AND c.item_id=:item
              AND c.kind=:kind AND c.key=:key
              AND cc.bottle_version_id=:bottle AND e.reviewed
            """),
            dict(
                release=release_id,
                item=item_id,
                kind=kind,
                key=key,
                bottle=row.bottle_version_id,
            ),
        ).all()
        if not verified or any(source.value != value for source in verified):
            return None
        if not set(evidence_ids) <= {source.evidence_id for source in verified}:
            return None
    return row.bottle_version_id


def published_prices(
    connection: Connection, release_id: UUID, item_id: UUID
) -> tuple[PublishedPrice, ...]:
    """Read immutable price observations inside the caller's transaction."""
    rows = connection.execute(
        text("""SELECT p.*,e.source_id,e.captured_at,
        i.abv,i.volume_ml FROM catalog_prices p
        JOIN catalog_releases r ON r.id=p.release_id
        JOIN catalog_items i ON (i.release_id,i.id)=(p.release_id,p.item_id)
        JOIN catalog_evidence e
            ON (e.release_id,e.id)=(p.release_id,p.evidence_id)
        WHERE p.release_id=:release_id AND p.item_id=:item_id AND r.sealed
        ORDER BY e.captured_at,p.id"""),
        {"release_id": release_id, "item_id": item_id},
    ).mappings()
    return tuple(
        PublishedPrice(
            row["id"],
            row["item_id"],
            row["evidence_id"],
            PriceObservation(
                row["source_id"],
                Bottle(row["bottle_version_id"], row["abv"], row["volume_ml"]),
                row["captured_at"],
                row["checked_on"],
                row["amount"],
                row["reviewed"],
                row["market"],
                row["currency"],
                row["unconditional"],
            ),
        )
        for row in rows
    )


def report_candidate_bottle(
    connection: Connection,
    release_id: UUID,
    item_id: UUID,
    claims: tuple[tuple[str, str, str, tuple[UUID, ...]], ...],
    budget_twd: Decimal | None,
    as_of: date,
) -> VerifiedReportCandidate | None:
    """Require reviewed source claims and the current price policy at save time."""
    bottle_version = reviewed_citation_bottle(connection, release_id, item_id, claims)
    if bottle_version is None:
        return None
    if release_id != current_release_id(connection):
        return None
    row = connection.execute(
        text("""
        SELECT abv,volume_ml FROM catalog_items
        WHERE release_id=:release AND id=:item AND reviewed
        """),
        dict(release=release_id, item=item_id),
    ).one()
    bottle = Bottle(bottle_version, row.abv, row.volume_ml)
    prices = published_prices(connection, release_id, item_id)
    qualified = qualified_prices(bottle, [price.observation for price in prices], as_of)
    selected = tuple(price for price in prices if price.observation in qualified)
    upper = max(
        (
            price.observation.amount
            for price in selected
            if price.observation.amount is not None
        ),
        default=None,
    )
    return (
        VerifiedReportCandidate(bottle_version, tuple(price.id for price in selected))
        if fits_budget(upper, budget_twd)
        else None
    )
