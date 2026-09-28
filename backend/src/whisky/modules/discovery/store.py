"""Transactional plan commands."""

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text

from whisky.modules.catalog.public import is_published_item
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.identity.public import actor_generation


class PlanConflict(ValueError):
    pass


@dataclass(frozen=True)
class Plan:
    id: UUID
    owner_id: UUID
    generation: int
    conditions_revision: int
    conditions: ResearchConditions


@dataclass(frozen=True)
class PlanCursor:
    updated_at: datetime
    id: UUID


@dataclass(frozen=True)
class PlanPage:
    items: tuple[Plan, ...]
    next_cursor: PlanCursor | None


class PlanStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def page(
        self, owner: UUID, limit: int = 20, cursor: PlanCursor | None = None
    ) -> PlanPage:
        if not 1 <= limit <= 50:
            raise ValueError("Page limit must be between 1 and 50")
        if cursor is not None and cursor.updated_at.utcoffset() is None:
            raise ValueError("Page cursor requires a timezone-aware timestamp")
        after = "AND (updated_at, id) < (:cursor_time, :cursor_id)" if cursor else ""
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            rows = connection.execute(
                text(
                    """
                SELECT id, owner_id, generation, conditions_revision, conditions,
                    updated_at FROM plans
                WHERE owner_id = :owner AND generation = :generation
                  AND deleted_at IS NULL
            """
                    + after
                    + " ORDER BY updated_at DESC, id DESC LIMIT :limit"
                ),
                dict(
                    owner=owner,
                    generation=generation,
                    limit=limit + 1,
                    cursor_time=cursor.updated_at if cursor else None,
                    cursor_id=cursor.id if cursor else None,
                ),
            ).all()
        visible = rows[:limit]
        items = tuple(
            Plan(
                row.id,
                row.owner_id,
                row.generation,
                row.conditions_revision,
                ResearchConditions.model_validate(row.conditions),
            )
            for row in visible
        )
        next_cursor = (
            PlanCursor(visible[-1].updated_at, visible[-1].id)
            if len(rows) > limit
            else None
        )
        return PlanPage(items, next_cursor)

    def create(
        self, owner: UUID, generation: int, key: str, conditions: ResearchConditions
    ) -> Plan:
        if not key.strip() or len(key) > 128:
            raise ValueError("Command key must contain 1 to 128 characters")
        payload = conditions.canonical_json()
        digest = sha256(payload.encode()).hexdigest()
        result = json.dumps(
            dict(
                generation=generation,
                conditions_revision=1,
                conditions=json.loads(payload),
            )
        )
        with self.engine.begin() as connection:
            if actor_generation(connection, owner, lock=True) != generation:
                raise PlanConflict("IDENTITY_CHANGED")
            reference = conditions.starting_bottle
            if reference is not None and not is_published_item(
                connection, reference.release_id, reference.item_id
            ):
                raise PlanConflict("CATALOG_REFERENCE_NOT_FOUND")
            target = uuid4()
            inserted = connection.execute(
                text("""
                INSERT INTO discovery_commands
                    (id, owner_id, scope, key, payload_hash, target_id, status, result)
                VALUES (:id, :owner, 'plans.create', :key, :hash, :target,
                        'completed', CAST(:result AS jsonb))
                ON CONFLICT (owner_id, scope, key) DO NOTHING
                RETURNING target_id
            """),
                dict(
                    id=uuid4(),
                    owner=owner,
                    key=key,
                    hash=digest,
                    target=target,
                    result=result,
                ),
            ).scalar()
            if inserted is None:
                receipt = connection.execute(
                    text("""
                    SELECT target_id, payload_hash, result FROM discovery_commands
                    WHERE owner_id = :owner AND scope = 'plans.create' AND key = :key
                """),
                    dict(owner=owner, key=key),
                ).one()
                if receipt.payload_hash != digest:
                    raise PlanConflict("IDEMPOTENCY_CONFLICT")
                saved = receipt.result
                if saved["generation"] != generation:
                    raise PlanConflict("IDENTITY_CHANGED")
                return Plan(
                    receipt.target_id,
                    owner,
                    saved["generation"],
                    saved["conditions_revision"],
                    ResearchConditions.model_validate(saved["conditions"]),
                )
            connection.execute(
                text("""
                INSERT INTO plans (id, owner_id, generation, conditions_revision,
                                   conditions_schema_version, conditions)
                VALUES (:id, :owner, :generation, 1, 1, CAST(:payload AS jsonb))
            """),
                dict(id=target, owner=owner, generation=generation, payload=payload),
            )
            return Plan(target, owner, generation, 1, conditions)

    def read(self, identifier: UUID, owner: UUID) -> Plan | None:
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            plan = self._read(connection, identifier, owner)
            return plan if plan is not None and plan.generation == generation else None

    @staticmethod
    def _read(
        connection: Connection, identifier: UUID, owner: UUID, *, lock: bool = False
    ) -> Plan | None:
        row = connection.execute(
            text(
                """
            SELECT id, owner_id, generation, conditions_revision, conditions
            FROM plans WHERE id = :id AND owner_id = :owner
              AND deleted_at IS NULL
        """
                + (" FOR UPDATE" if lock else "")
            ),
            dict(id=identifier, owner=owner),
        ).first()
        if row is None:
            return None
        return Plan(
            row.id,
            row.owner_id,
            row.generation,
            row.conditions_revision,
            ResearchConditions.model_validate(row.conditions),
        )
