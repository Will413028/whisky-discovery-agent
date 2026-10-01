"""Owned plan export records, joined to the caller's consistent snapshot."""

from collections.abc import Iterator
from datetime import datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import Connection, text

from whisky.platform.export_contracts import ExportRecord


class PlanExportV1(ExportRecord):
    id: UUID
    generation: int
    conditions_revision: int
    conditions_schema_version: int
    conditions: dict[str, JsonValue]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


def export_plans(
    connection: Connection, owner: UUID, generation: int
) -> Iterator[dict[str, JsonValue]]:
    query = text("""
        SELECT to_jsonb(export_row) FROM (
            SELECT id,generation,conditions_revision,conditions_schema_version,
                conditions,created_at,updated_at,deleted_at
            FROM plans WHERE owner_id=:owner AND generation=:generation
                AND deleted_at IS NULL
            ORDER BY created_at,id
        ) export_row
    """)
    yield from (
        connection.execution_options(stream_results=True)
        .execute(query, dict(owner=owner, generation=generation))
        .scalars()
    )
