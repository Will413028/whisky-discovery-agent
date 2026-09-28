"""Plan snapshot access inside another module's product transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from whisky.modules.discovery.conditions import ResearchConditions as ResearchConditions

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from whisky.modules.discovery.store import Plan


def locked_plan(connection: Connection, plan_id: UUID, owner: UUID) -> Plan | None:
    """Caller locks identity first; retain this plan lock until task commit."""
    from whisky.modules.discovery.store import PlanStore

    return PlanStore._read(connection, plan_id, owner, lock=True)
