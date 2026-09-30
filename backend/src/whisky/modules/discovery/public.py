"""Plan snapshot access inside another module's product transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from whisky.modules.discovery.condition_patch import ConditionPatch as ConditionPatch
from whisky.modules.discovery.condition_patch import (
    apply_condition_patch as apply_condition_patch,
)
from whisky.modules.discovery.conditions import CatalogReference as CatalogReference
from whisky.modules.discovery.conditions import ResearchConditions as ResearchConditions
from whisky.modules.discovery.conditions_v1 import (
    ResearchConditionsV1 as ResearchConditionsV1,
)
from whisky.platform.domain_errors import DomainRejection

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from whisky.modules.discovery.store import Plan


def locked_plan(connection: Connection, plan_id: UUID, owner: UUID) -> Plan | None:
    """Caller locks identity first; retain this plan lock until task commit."""
    from whisky.modules.discovery.store import PlanStore

    return PlanStore._read(connection, plan_id, owner, lock=True)


def owned_plan(connection: Connection, plan_id: UUID, owner: UUID) -> Plan | None:
    """Read a live owned plan without acquiring a write lock."""
    from whisky.modules.discovery.store import PlanStore

    return PlanStore._read(connection, plan_id, owner)


def change_conditions(
    connection: Connection,
    plan_id: UUID,
    owner: UUID,
    revision: int,
    conditions: ResearchConditionsV1,
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


def actor_plans_closed(connection: Connection, owner: UUID, generation: int) -> bool:
    """Recovery fence for all plans in a removed identity generation."""
    from sqlalchemy import text

    return (
        connection.scalar(
            text("""
        SELECT count(*) FROM plans
        WHERE owner_id=:owner AND generation=:generation AND deleted_at IS NULL
        """),
            dict(owner=owner, generation=generation),
        )
        == 0
    )


def plan_control_effect_present(
    connection: Connection,
    plan_id: UUID,
    owner: UUID,
    generation: int,
    *,
    deleted: bool,
    expected_revision: int,
    new_conditions: ResearchConditionsV1 | None,
) -> bool:
    """Recovery read of the plan's own fence and revision."""
    from sqlalchemy import text

    plan = (
        connection.execute(
            text("""
            SELECT owner_id,generation,deleted_at,conditions_revision,conditions
            FROM plans WHERE id=:id
            """),
            dict(id=plan_id),
        )
        .mappings()
        .first()
    )
    if plan is None:
        return True
    if plan["owner_id"] != owner or plan["generation"] != generation:
        raise ValueError("control target belongs to another scope")
    if deleted:
        return plan["deleted_at"] is not None
    if plan["deleted_at"] is not None:
        return True
    if plan["conditions_revision"] < expected_revision + 1:
        return False
    return not (
        plan["conditions_revision"] == expected_revision + 1
        and ResearchConditionsV1.model_validate(plan["conditions"]) != new_conditions
    )
