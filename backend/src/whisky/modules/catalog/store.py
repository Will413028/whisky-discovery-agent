"""Transactional PostgreSQL catalog publication and immutable-reference reads."""

from uuid import UUID

from sqlalchemy import Engine, text

from whisky.modules.catalog.domain import (
    Bottle,
    CatalogFact,
    CatalogItem,
    CatalogRelease,
    Evidence,
    FlavorTag,
    validate_release,
)


class CatalogStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

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
