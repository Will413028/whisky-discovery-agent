"""Plan snapshot access inside another module's product transaction."""

from uuid import UUID

from sqlalchemy import Connection

from whisky.modules.discovery.store import Plan, PlanStore


def locked_plan(connection: Connection, plan_id: UUID, owner: UUID) -> Plan | None:
    """Caller locks identity first; retain this plan lock until task commit."""
    return PlanStore._read(connection, plan_id, owner, lock=True)
