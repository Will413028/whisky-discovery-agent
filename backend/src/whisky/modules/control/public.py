"""Export retained user condition changes without operational credentials."""

from collections.abc import Iterator
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import Connection, text
from sqlalchemy.engine import ScalarResult

from whisky.modules.discovery.public import ResearchConditionsV1
from whisky.platform.export_contracts import ExportRecord


class ConditionChangeExportV1(ExportRecord):
    id: UUID
    target_id: UUID
    expected_revision: int
    status: Literal[
        "pending",
        "intent_confirmed",
        "effect_applied",
        "effect_rejected",
        "completed",
        "rejected",
    ]
    new_conditions: ResearchConditionsV1
    created_at: datetime
    updated_at: datetime


def export_condition_changes(
    connection: Connection, owner: UUID, generation: int, plan_ids: tuple[UUID, ...]
) -> Iterator[dict[str, JsonValue]]:
    rows: ScalarResult[dict[str, JsonValue]] = (
        connection.execution_options(stream_results=True)
        .execute(
            text("""
        SELECT to_jsonb(export_row) FROM (
            SELECT id,target_id,expected_revision,status,new_conditions,
                created_at,updated_at FROM control_commands
            WHERE owner_id=:owner AND generation=:generation
                AND kind='plan.change_conditions' AND target_id=ANY(:plan_ids)
            ORDER BY created_at,id
        ) export_row
    """),
            dict(owner=owner, generation=generation, plan_ids=list(plan_ids)),
        )
        .scalars()
    )
    yield from rows
