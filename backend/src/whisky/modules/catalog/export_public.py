"""Only the sealed catalog records referenced by an owned export."""

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import Connection, text
from sqlalchemy.engine import ScalarResult

from whisky.platform.export_contracts import ExportRecord, ExportRelation


class CatalogItemExportV1(ExportRecord):
    release_id: UUID
    id: UUID
    bottle_version_id: UUID
    name: str
    abv: Decimal | None
    volume_ml: int | None
    reviewed_on: date | None


class CatalogPriceExportV1(ExportRecord):
    release_id: UUID
    id: UUID
    item_id: UUID
    evidence_id: UUID
    bottle_version_id: UUID
    amount: Decimal | None
    checked_on: date | None
    market: str
    currency: str
    unconditional: bool


class CatalogEvidenceExportV1(ExportRecord):
    release_id: UUID
    id: UUID
    source_id: UUID
    bottle_version_id: UUID
    url: str
    publisher: str | None
    captured_at: datetime
    checked_on: date


def export_references(
    connection: Connection,
    scopes: dict[str, ExportRelation],
) -> Iterator[tuple[str, dict[str, JsonValue]]]:
    for section, table, columns in (
        (
            "catalogItems",
            "catalog_items",
            "c.release_id,c.id,c.bottle_version_id,c.name,c.abv,c.volume_ml,c.reviewed_on",
        ),
        (
            "catalogPrices",
            "catalog_prices",
            "c.release_id,c.id,c.item_id,c.evidence_id,c.bottle_version_id,c.amount,c.checked_on,c.market,c.currency,c.unconditional",
        ),
        (
            "catalogEvidence",
            "catalog_evidence",
            "c.release_id,c.id,c.source_id,c.bottle_version_id,c.url,c.publisher,c.captured_at,c.checked_on",
        ),
    ):
        scope = scopes[section]
        reference_sql = scope.sql
        if section == "catalogEvidence":
            prices = scopes["catalogPrices"]
            if (prices.owner, prices.generation) != (scope.owner, scope.generation):
                raise ValueError("EXPORT_SCOPE_MISMATCH")
            reference_sql = (
                scope.sql + " UNION SELECT c.release_id,c.evidence_id AS id "
                "FROM catalog_prices c JOIN (" + prices.sql + ") k "
                "ON k.release_id=c.release_id AND k.id=c.id"
            )
        query = f"""
            SELECT to_jsonb(export_row) FROM (
                SELECT {columns} FROM {table} c
                JOIN ({reference_sql}) k
                    ON k.release_id=c.release_id AND k.id=c.id
                JOIN catalog_releases r ON r.id=c.release_id
                WHERE r.sealed AND c.reviewed ORDER BY c.release_id,c.id
            ) export_row
        """
        rows: ScalarResult[dict[str, JsonValue]] = (
            connection.execution_options(stream_results=True)
            .execute(
                text(query),
                scope.parameters,
            )
            .scalars()
        )
        for row in rows:
            yield section, row
