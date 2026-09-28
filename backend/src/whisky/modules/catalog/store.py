"""Transactional PostgreSQL catalog publication and immutable-reference reads."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Engine, text

from whisky.modules.catalog.domain import (
    Bottle,
    CatalogCandidate,
    CatalogFact,
    CatalogItem,
    CatalogRelease,
    Evidence,
    FlavorTag,
    PriceObservation,
    PublishedPrice,
    fits_budget,
    qualified_prices,
    validate_release,
)


class CatalogStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def candidates(
        self, as_of: date, budget: Decimal | None
    ) -> tuple[CatalogCandidate, ...]:
        with self.engine.connect() as connection:
            release_id = connection.scalar(
                text("""SELECT id FROM catalog_releases
                WHERE sealed ORDER BY published_at DESC LIMIT 1""")
            )
            if release_id is None:
                return ()
            identifiers = connection.scalars(
                text("""SELECT id FROM catalog_items
                WHERE release_id=:release_id AND reviewed ORDER BY id"""),
                {"release_id": release_id},
            ).all()
        candidates = []
        for identifier in identifiers:
            item = self.item(release_id, identifier)
            if item is None:
                continue
            prices = self.prices(release_id, identifier)
            qualified = qualified_prices(
                item.bottle, [price.observation for price in prices], as_of
            )
            candidate = CatalogCandidate(
                release_id,
                item,
                tuple(price for price in prices if price.observation in qualified),
            )
            if fits_budget(candidate.price_upper_bound, budget):
                candidates.append(candidate)
        return tuple(candidates)

    def prices(self, release_id: UUID, item_id: UUID) -> tuple[PublishedPrice, ...]:
        with self.engine.connect() as connection:
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

    def publish(self, release: CatalogRelease) -> None:
        validate_release(release)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO catalog_releases (id, published_at, sealed) "
                    "VALUES (:id, :published_at, false)"
                ),
                {"id": release.id, "published_at": release.published_at},
            )
            for evidence in release.evidence:
                connection.execute(
                    text("""INSERT INTO catalog_evidence
                    (release_id,id,source_id,bottle_version_id,url,captured_at,checked_on,reviewed)
                    VALUES (:release_id,:id,:source_id,:bottle_version_id,
                            :url,:captured_at,:checked_on,:reviewed)"""),
                    {
                        "release_id": release.id,
                        "id": evidence.id,
                        "source_id": evidence.source_id,
                        "bottle_version_id": evidence.bottle_version_id,
                        "url": evidence.url,
                        "captured_at": evidence.captured_at,
                        "checked_on": evidence.checked_on,
                        "reviewed": evidence.reviewed,
                    },
                )
            for item in release.items:
                connection.execute(
                    text("""INSERT INTO catalog_items
                    (release_id,id,bottle_version_id,abv,volume_ml,name,reviewed)
                    VALUES (:release_id,:id,:bottle_version_id,
                            :abv,:volume_ml,:name,:reviewed)"""),
                    {
                        "release_id": release.id,
                        "id": item.id,
                        "bottle_version_id": item.bottle.version_id,
                        "abv": item.bottle.abv,
                        "volume_ml": item.bottle.volume_ml,
                        "name": item.name,
                        "reviewed": item.reviewed,
                    },
                )
                claims = [
                    ("fact", fact.field, fact.value, fact.evidence_ids)
                    for fact in item.facts
                ]
                claims.extend(
                    ("tag", tag.label, tag.label, tag.evidence_ids)
                    for tag in item.flavor_tags
                )
                for kind, key, value, identifiers in claims:
                    parameters = {
                        "release_id": release.id,
                        "item_id": item.id,
                        "kind": kind,
                        "key": key,
                        "value": value,
                    }
                    connection.execute(
                        text("""INSERT INTO catalog_claims
                        (release_id,item_id,kind,key,value)
                        VALUES (:release_id,:item_id,:kind,:key,:value)"""),
                        parameters,
                    )
                    for identifier in identifiers:
                        connection.execute(
                            text("""INSERT INTO catalog_citations
                            (release_id,item_id,kind,key,evidence_id,bottle_version_id)
                            VALUES (:release_id,:item_id,:kind,:key,
                                    :evidence_id,:bottle_version_id)"""),
                            {
                                **parameters,
                                "evidence_id": identifier,
                                "bottle_version_id": item.bottle.version_id,
                            },
                        )
            for price in release.prices:
                observation = price.observation
                connection.execute(
                    text("""INSERT INTO catalog_prices
                    (release_id,id,item_id,evidence_id,bottle_version_id,amount,
                     checked_on,reviewed,market,currency,unconditional)
                    VALUES (:release_id,:id,:item_id,:evidence_id,:bottle_version_id,
                            :amount,:checked_on,:reviewed,:market,:currency,:unconditional)
                    """),
                    {
                        "release_id": release.id,
                        "id": price.id,
                        "item_id": price.item_id,
                        "evidence_id": price.evidence_id,
                        "bottle_version_id": observation.bottle.version_id,
                        "amount": observation.amount,
                        "checked_on": observation.checked_on,
                        "reviewed": observation.reviewed,
                        "market": observation.market,
                        "currency": observation.currency,
                        "unconditional": observation.unconditional,
                    },
                )
            connection.execute(
                text("UPDATE catalog_releases SET sealed=true WHERE id=:id"),
                {"id": release.id},
            )

    def item(self, release_id: UUID, item_id: UUID) -> CatalogItem | None:
        parameters = {"release_id": release_id, "item_id": item_id}
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("""SELECT i.* FROM catalog_items i
                JOIN catalog_releases r ON r.id=i.release_id
                WHERE i.release_id=:release_id AND i.id=:item_id
                    AND r.sealed AND i.reviewed"""),
                    parameters,
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            citations: dict[tuple[str, str], list[UUID]] = {}
            for citation in connection.execute(
                text("""SELECT kind,key,evidence_id FROM catalog_citations
                WHERE release_id=:release_id AND item_id=:item_id
                ORDER BY evidence_id"""),
                parameters,
            ).mappings():
                citations.setdefault((citation["kind"], citation["key"]), []).append(
                    citation["evidence_id"]
                )
            facts = []
            tags = []
            for claim in connection.execute(
                text("""SELECT kind,key,value FROM catalog_claims
                WHERE release_id=:release_id AND item_id=:item_id ORDER BY kind,key"""),
                parameters,
            ).mappings():
                identifiers = tuple(citations[(claim["kind"], claim["key"])])
                if claim["kind"] == "fact":
                    facts.append(CatalogFact(claim["key"], claim["value"], identifiers))
                else:
                    tags.append(FlavorTag(claim["value"], identifiers))
            return CatalogItem(
                row["id"],
                Bottle(row["bottle_version_id"], row["abv"], row["volume_ml"]),
                row["name"],
                tuple(facts),
                tuple(tags),
                row["reviewed"],
            )

    def evidence(self, release_id: UUID, evidence_id: UUID) -> Evidence | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("""SELECT e.* FROM catalog_evidence e
                JOIN catalog_releases r ON r.id=e.release_id
                WHERE e.release_id=:release_id AND e.id=:evidence_id
                    AND r.sealed AND e.reviewed"""),
                    {"release_id": release_id, "evidence_id": evidence_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return Evidence(
                row["id"],
                row["source_id"],
                row["bottle_version_id"],
                row["url"],
                row["captured_at"],
                row["checked_on"],
                row["reviewed"],
            )
