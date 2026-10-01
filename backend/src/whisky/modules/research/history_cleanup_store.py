"""Bounded discovery of research tombstones whose parents were deleted."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Engine, text

from whisky.modules.discovery.public import locked_plan_deletion_fence
from whisky.modules.identity.public import control_actor_state
from whisky.modules.research.domain import workflow_id_for


@dataclass(frozen=True)
class HistoryCleanupPage:
    workflow_ids: tuple[str, ...]
    cursor: str | None


def deleted_history_page(
    engine: Engine, cursor: str | None = None, *, page_size: int = 100
) -> HistoryCleanupPage:
    if not 1 <= page_size <= 100:
        raise ValueError("Cleanup pages must contain between 1 and 100 tasks")
    after = UUID(cursor) if cursor is not None else None
    with engine.begin() as connection:
        rows = (
            connection.execute(
                text(
                    "SELECT id,owner_id,plan_id,generation FROM research_tasks "
                    "WHERE NOT write_allowed AND status='cancelled' "
                    "AND conditions='{}'::jsonb "
                    "AND (CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid)) "
                    "ORDER BY id LIMIT :limit"
                ),
                dict(after=after, limit=page_size),
            )
            .mappings()
            .all()
        )
        targets = []
        for row in sorted(rows, key=lambda row: (row["owner_id"], row["plan_id"])):
            actor = control_actor_state(connection, row["owner_id"], lock=True)
            actor_deleted = (
                actor is None
                or actor[0] > row["generation"]
                or (actor == (row["generation"], False))
            )
            if actor_deleted or locked_plan_deletion_fence(
                connection, row["plan_id"], row["owner_id"], row["generation"]
            ):
                targets.append(workflow_id_for(row["id"]))
        return HistoryCleanupPage(
            tuple(targets), str(rows[-1]["id"]) if len(rows) == page_size else None
        )
