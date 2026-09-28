"""Product receipts for VM-external control intents and fenced effects."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, text

from whisky.modules.discovery.public import (
    ResearchConditions,
    change_conditions,
    delete_actor_plans,
    delete_plan,
    locked_plan,
)
from whisky.modules.identity.public import (
    control_actor_state,
    disable_actor,
)
from whisky.modules.research.public import (
    cancel_task,
    close_actor_tasks,
    close_plan_tasks,
    controlled_workflow_ids,
    task_plan,
)
from whisky.platform.domain_errors import DomainRejection

ControlKind = Literal[
    "task.cancel", "plan.change_conditions", "plan.delete", "actor.delete"
]
ControlStatus = Literal[
    "pending",
    "intent_confirmed",
    "effect_applied",
    "effect_rejected",
    "completed",
    "rejected",
]


class ControlConflict(ValueError):
    pass


@dataclass(frozen=True)
class ControlReceipt:
    id: UUID
    owner_id: UUID
    generation: int
    kind: ControlKind
    target_id: UUID
    target_generation: int
    expected_revision: int
    key: str
    payload_hash: str
    status: ControlStatus
    result: dict[str, str] | None
    created_at: datetime
    new_conditions: ResearchConditions | None = None

    @property
    def workflow_id(self) -> str:
        return (
            f"whisky-control-{self.kind}-{self.target_id.hex}-"
            f"{self.target_generation}-{self.expected_revision}-{self.id.hex}"
        )


class ControlStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def reserve(
        self,
        owner: UUID,
        generation: int,
        kind: ControlKind,
        target_id: UUID,
        key: str,
        *,
        expected_revision: int = 0,
        conditions: ResearchConditions | None = None,
    ) -> ControlReceipt:
        try:
            key_uuid = UUID(key)
        except ValueError:
            raise ValueError("Control key must be a UUIDv4") from None
        if key_uuid.version != 4:
            raise ValueError("Control key must be a UUIDv4")
        key = str(key_uuid)
        if kind == "plan.change_conditions":
            if expected_revision < 1 or conditions is None:
                raise ValueError("Condition changes require a revision and conditions")
        elif expected_revision != 0 or conditions is not None:
            raise ValueError("Only condition changes carry a revision and conditions")
        payload = json.dumps(
            dict(
                kind=kind,
                targetId=str(target_id),
                expectedRevision=expected_revision,
                conditions=json.loads(conditions.canonical_json())
                if conditions
                else None,
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = sha256(payload.encode()).hexdigest()
        with self.engine.begin() as connection:
            existing = self._by_key(connection, owner, kind, key)
            if existing is not None:
                return self._replay(existing, generation, digest)
            actor = control_actor_state(connection, owner, lock=True)
            if actor != (generation, True):
                raise ControlConflict("IDENTITY_CHANGED")
            existing = self._by_key(connection, owner, kind, key)
            if existing is not None:
                return self._replay(existing, generation, digest)
            self._validate_target(
                connection, owner, generation, kind, target_id, expected_revision
            )
            identifier = uuid4()
            row = (
                connection.execute(
                    text("""
                INSERT INTO control_commands
                    (id,owner_id,generation,kind,target_id,target_generation,
                     expected_revision,key,payload_hash,new_conditions,status)
                VALUES (:id,:owner,:generation,:kind,:target,:generation,
                        :revision,:key,:hash,CAST(:conditions AS jsonb),'pending')
                RETURNING *
                """),
                    dict(
                        id=identifier,
                        owner=owner,
                        generation=generation,
                        kind=kind,
                        target=target_id,
                        revision=expected_revision,
                        key=key,
                        hash=digest,
                        conditions=conditions.canonical_json() if conditions else None,
                    ),
                )
                .mappings()
                .one()
            )
            return self._view(row)

    def read(self, identifier: UUID, owner: UUID) -> ControlReceipt | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT * FROM control_commands "
                        "WHERE id=:id AND owner_id=:owner"
                    ),
                    dict(id=identifier, owner=owner),
                )
                .mappings()
                .first()
            )
            return self._view(row) if row is not None else None

    def load_for_activity(self, identifier: UUID) -> ControlReceipt:
        """Internal worker lookup; HTTP must use the owner-scoped read method."""
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM control_commands WHERE id=:id"),
                    dict(id=identifier),
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ControlConflict("NOT_FOUND")
            return self._view(row)

    def affected_workflows(self, identifier: UUID) -> tuple[str, ...]:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM control_commands WHERE id=:id"),
                    dict(id=identifier),
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ControlConflict("NOT_FOUND")
            if row["status"] != "completed":
                return ()
            return controlled_workflow_ids(
                connection,
                row["owner_id"],
                row["kind"],
                row["target_id"],
                row["target_generation"],
                row["expected_revision"],
            )

    def confirm_intent(self, identifier: UUID) -> ControlReceipt:
        """Called only after the immutable outside intent was written and read back."""
        with self.engine.begin() as connection:
            row = self._locked(connection, identifier)
            if row["status"] == "pending":
                row = (
                    connection.execute(
                        text("""
                    UPDATE control_commands
                    SET status='intent_confirmed',updated_at=now()
                    WHERE id=:id RETURNING *
                    """),
                        dict(id=identifier),
                    )
                    .mappings()
                    .one()
                )
            return self._view(row)

    def apply(self, identifier: UUID) -> ControlReceipt:
        """An idempotent DB effect; identity is locked before plan and task rows."""
        with self.engine.begin() as connection:
            preliminary = (
                connection.execute(
                    text("SELECT * FROM control_commands WHERE id=:id"),
                    dict(id=identifier),
                )
                .mappings()
                .first()
            )
            if preliminary is None:
                raise ControlConflict("NOT_FOUND")
            if preliminary["status"] == "pending":
                raise ControlConflict("INTENT_UNCONFIRMED")
            if preliminary["status"] in {
                "effect_applied",
                "effect_rejected",
                "completed",
                "rejected",
            }:
                return self._view(preliminary)
            actor = control_actor_state(connection, preliminary["owner_id"], lock=True)
            row = self._locked(connection, identifier)
            if row["status"] in {
                "effect_applied",
                "effect_rejected",
                "completed",
                "rejected",
            }:
                return self._view(row)
            if row["status"] != "intent_confirmed":
                raise ControlConflict("INTENT_UNCONFIRMED")
            try:
                if actor != (row["generation"], True):
                    raise DomainRejection("IDENTITY_CHANGED")
                with connection.begin_nested():
                    self._effect(connection, row)
            except DomainRejection as error:
                outcome = "rejected"
                status = "effect_rejected"
                result = dict(outcome=outcome, code=error.code)
            else:
                outcome = "completed"
                status = "effect_applied"
                result = dict(outcome=outcome)
            result["effectAt"] = datetime.now(UTC).isoformat()
            updated = (
                connection.execute(
                    text("""
                UPDATE control_commands SET status=:status,
                    result=CAST(:result AS jsonb),updated_at=now()
                WHERE id=:id RETURNING *
                """),
                    dict(id=identifier, status=status, result=json.dumps(result)),
                )
                .mappings()
                .one()
            )
            return self._view(updated)

    def confirm_result(self, identifier: UUID) -> ControlReceipt:
        """Called only after the outside result was written and read back."""
        with self.engine.begin() as connection:
            row = self._locked(connection, identifier)
            if row["status"] in {"completed", "rejected"}:
                return self._view(row)
            status = {
                "effect_applied": "completed",
                "effect_rejected": "rejected",
            }.get(row["status"])
            if status is None:
                raise ControlConflict("RESULT_UNCONFIRMED")
            updated = (
                connection.execute(
                    text("""
                UPDATE control_commands SET status=:status,updated_at=now()
                WHERE id=:id RETURNING *
                """),
                    dict(id=identifier, status=status),
                )
                .mappings()
                .one()
            )
            return self._view(updated)

    @staticmethod
    def _effect(connection: Connection, row: RowMapping) -> None:
        owner: UUID = row["owner_id"]
        target: UUID = row["target_id"]
        generation: int = row["generation"]
        kind: ControlKind = row["kind"]
        if kind == "actor.delete":
            if target != owner:
                raise DomainRejection("NOT_FOUND")
            close_actor_tasks(connection, owner, generation)
            delete_actor_plans(connection, owner, generation)
            try:
                disable_actor(connection, owner, generation)
            except ValueError as error:
                # This follows child writes, so a failed final step must roll
                # the whole transaction back instead of recording a rejection.
                raise RuntimeError("identity changed during actor deletion") from error
            return
        if kind == "task.cancel":
            plan_id = task_plan(connection, target, owner)
            if plan_id is None:
                raise DomainRejection("NOT_FOUND")
            plan = locked_plan(connection, plan_id, owner)
            if plan is None or plan.generation != generation:
                raise DomainRejection("NOT_FOUND")
            cancel_task(connection, target, owner, generation, plan_id)
            return
        plan = locked_plan(connection, target, owner)
        if plan is None or plan.generation != generation:
            raise DomainRejection("NOT_FOUND")
        if kind == "plan.change_conditions":
            if plan.conditions_revision != row["expected_revision"]:
                raise DomainRejection("REVISION_CONFLICT")
            conditions = ResearchConditions.model_validate(row["new_conditions"])
            change_conditions(
                connection, target, owner, plan.conditions_revision, conditions
            )
            close_plan_tasks(
                connection,
                owner,
                target,
                status="superseded",
                newer_revision=plan.conditions_revision + 1,
            )
            return
        if kind == "plan.delete":
            close_plan_tasks(connection, owner, target, status="cancelled")
            delete_plan(connection, target, owner)
            return
        raise RuntimeError("Unknown persisted control kind")

    @staticmethod
    def _validate_target(
        connection: Connection,
        owner: UUID,
        generation: int,
        kind: ControlKind,
        target_id: UUID,
        expected_revision: int,
    ) -> None:
        if kind == "actor.delete":
            if target_id != owner:
                raise ControlConflict("NOT_FOUND")
            return
        if kind == "task.cancel":
            plan_id = task_plan(connection, target_id, owner)
            if plan_id is None:
                raise ControlConflict("NOT_FOUND")
            plan = locked_plan(connection, plan_id, owner)
        else:
            plan = locked_plan(connection, target_id, owner)
        if plan is None or plan.generation != generation:
            raise ControlConflict("NOT_FOUND")
        if kind == "plan.change_conditions" and (
            plan.conditions_revision != expected_revision
        ):
            raise ControlConflict("REVISION_CONFLICT")

    @staticmethod
    def _by_key(
        connection: Connection, owner: UUID, kind: ControlKind, key: str
    ) -> RowMapping | None:
        return (
            connection.execute(
                text("""
            SELECT * FROM control_commands
            WHERE owner_id=:owner AND kind=:kind AND key=:key
            """),
                dict(owner=owner, kind=kind, key=key),
            )
            .mappings()
            .first()
        )

    @staticmethod
    def _locked(connection: Connection, identifier: UUID) -> RowMapping:
        row = (
            connection.execute(
                text("SELECT * FROM control_commands WHERE id=:id FOR UPDATE"),
                dict(id=identifier),
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ControlConflict("NOT_FOUND")
        return row

    @staticmethod
    def _replay(row: RowMapping, generation: int, digest: str) -> ControlReceipt:
        deleted_actor_replay = (
            row["kind"] == "actor.delete"
            and row["status"] in {"effect_applied", "completed"}
            and generation == row["generation"] + 1
        )
        if row["generation"] != generation and not deleted_actor_replay:
            raise ControlConflict("IDENTITY_CHANGED")
        if row["payload_hash"] != digest:
            raise ControlConflict("IDEMPOTENCY_CONFLICT")
        return ControlStore._view(row)

    @staticmethod
    def _view(row: RowMapping) -> ControlReceipt:
        return ControlReceipt(
            id=row["id"],
            owner_id=row["owner_id"],
            generation=row["generation"],
            kind=cast(ControlKind, row["kind"]),
            target_id=row["target_id"],
            target_generation=row["target_generation"],
            expected_revision=row["expected_revision"],
            key=row["key"],
            payload_hash=row["payload_hash"],
            status=cast(ControlStatus, row["status"]),
            result=row["result"],
            created_at=row["created_at"],
            new_conditions=(
                ResearchConditions.model_validate(row["new_conditions"])
                if row["new_conditions"] is not None
                else None
            ),
        )
