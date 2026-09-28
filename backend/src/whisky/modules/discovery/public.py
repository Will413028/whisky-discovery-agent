"""Plan snapshot access inside another module's product transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from whisky.modules.discovery.conditions import ResearchConditions as ResearchConditions
from whisky.platform.domain_errors import DomainRejection

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from whisky.modules.discovery.store import Plan


def locked_plan(connection: Connection, plan_id: UUID, owner: UUID) -> Plan | None:
    """Caller locks identity first; retain this plan lock until task commit."""
    from whisky.modules.discovery.store import PlanStore

    return PlanStore._read(connection, plan_id, owner, lock=True)


def change_conditions(
    connection: Connection,
    plan_id: UUID,
    owner: UUID,
    revision: int,
    conditions: ResearchConditions,
) -> None:
    """Caller holds the owner and plan locks; update only the expected revision."""
    from sqlalchemy import text

    from whisky.modules.catalog.public import is_published_item

    reference = conditions.starting_bottle
    if reference is not None and not is_published_item(
        connection, reference.release_id, reference.item_id
    ):
        raise DomainRejection("CATALOG_REFERENCE_NOT_FOUND")
    changed = connection.execute(
        text("""
        UPDATE plans SET conditions_revision=conditions_revision+1,
            conditions=CAST(:conditions AS jsonb), updated_at=now()
        WHERE id=:plan AND owner_id=:owner AND conditions_revision=:revision
          AND deleted_at IS NULL
        RETURNING id
        """),
        dict(
            plan=plan_id,
            owner=owner,
            revision=revision,
            conditions=conditions.canonical_json(),
        ),
    ).scalar()
    if changed is None:
        raise DomainRejection("REVISION_CONFLICT")


def delete_plan(connection: Connection, plan_id: UUID, owner: UUID) -> None:
    """Tombstone an owned plan after its child tasks have been fenced."""
    from sqlalchemy import text

    connection.execute(
        text("""
        UPDATE plans SET deleted_at=now(), updated_at=now()
        WHERE id=:plan AND owner_id=:owner AND deleted_at IS NULL
        """),
        dict(plan=plan_id, owner=owner),
    )


def delete_actor_plans(connection: Connection, owner: UUID, generation: int) -> None:
    """Tombstone every plan in the actor generation being removed."""
    from sqlalchemy import text

    connection.execute(
        text("""
        UPDATE plans SET deleted_at=now(), updated_at=now()
        WHERE owner_id=:owner AND generation<=:generation AND deleted_at IS NULL
        """),
        dict(owner=owner, generation=generation),
    )
