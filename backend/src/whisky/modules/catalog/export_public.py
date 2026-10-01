"""Only the sealed catalog records referenced by an owned export."""

import json
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import Connection, text
from sqlalchemy.engine import ScalarResult

from whisky.platform.export_contracts import ExportRecord


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
    *,
    items: set[tuple[str, str]],
    evidence: set[tuple[str, str]],
    prices: set[tuple[str, str]],
) -> Iterator[tuple[str, dict[str, JsonValue]]]:
    evidence = set(evidence)
    for section, table, keys, columns in (
        (
            "catalogItems",
            "catalog_items",
            items,
            "c.release_id,c.id,c.bottle_version_id,c.name,c.abv,c.volume_ml,c.reviewed_on",
        ),
        (
            "catalogPrices",
            "catalog_prices",
            prices,
            "c.release_id,c.id,c.item_id,c.evidence_id,c.bottle_version_id,c.amount,c.checked_on,c.market,c.currency,c.unconditional",
        ),
        (
            "catalogEvidence",
            "catalog_evidence",
            evidence,
            "c.release_id,c.id,c.source_id,c.bottle_version_id,c.url,c.publisher,c.captured_at,c.checked_on",
        ),
    ):
        if not keys:
            continue
        query = f"""
            SELECT to_jsonb(export_row) FROM (
                SELECT {columns} FROM {table} c
                JOIN jsonb_to_recordset(CAST(:keys AS jsonb))
                    AS k(release_id uuid,id uuid)
                    ON k.release_id=c.release_id AND k.id=c.id
                JOIN catalog_releases r ON r.id=c.release_id
                WHERE r.sealed AND c.reviewed ORDER BY c.release_id,c.id
            ) export_row
        """
        rows: ScalarResult[dict[str, JsonValue]] = (
            connection.execution_options(stream_results=True)
            .execute(
                text(query),
                {
                    "keys": json.dumps(
                        [
                            dict(release_id=release, id=id)
                            for release, id in sorted(keys)
                        ]
                    )
                },
            )
            .scalars()
        )
        for row in rows:
            if section == "catalogPrices":
                evidence.add((str(row["release_id"]), str(row["evidence_id"])))
            yield section, row
