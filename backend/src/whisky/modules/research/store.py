"""Product-owned research acceptance receipts and task projections."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, text

from whisky.modules.discovery.public import locked_plan
from whisky.modules.identity.public import actor_generation
from whisky.modules.research.domain import workflow_id_for
from whisky.modules.research.views import TaskView


class ResearchConflict(ValueError):
    pass


@dataclass(frozen=True)
class StartReceipt:
    id: UUID
    task_id: UUID
    workflow_id: str
    acceptance: Literal["acceptance_pending", "accepted"]


class ResearchStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def reserve(
        self, owner: UUID, generation: int, plan_id: UUID, revision: int, key: str
    ) -> StartReceipt:
        if not key.strip() or len(key) > 128 or revision < 1:
            raise ValueError("Invalid research command key or revision")
        digest = sha256(
            json.dumps(
                dict(plan_id=str(plan_id), revision=revision), sort_keys=True
            ).encode()
        ).hexdigest()
        with self.engine.begin() as connection:
            self._identity(connection, owner, generation)
            existing = self._receipt(connection, owner, key=key)
            if existing is not None:
                if existing["payload_hash"] != digest:
                    raise ResearchConflict("IDEMPOTENCY_CONFLICT")
                if existing["generation"] != generation:
                    raise ResearchConflict("IDENTITY_CHANGED")
                if existing["status"] == "accepted":
                    return self._view(existing)
                if existing["task_status"] == "completed":
                    return self._save_acceptance(
                        connection, existing, existing["temporal_run_id"]
                    )
            plan = locked_plan(connection, plan_id, owner)
            if plan is None or plan.generation != generation:
                raise ResearchConflict("NOT_FOUND")
            if plan.conditions_revision != revision:
                raise ResearchConflict("REVISION_CONFLICT")
            if existing is not None:
                if not existing["write_allowed"]:
                    raise ResearchConflict("TASK_NOT_WRITABLE")
                return self._view(existing)
            task_id, command_id, thread_id = uuid4(), uuid4(), uuid4()
            workflow_id = workflow_id_for(task_id)
            connection.execute(
                text("""
                INSERT INTO research_tasks
                    (id, owner_id, plan_id, generation, conditions_revision,
                     conditions_schema_version, conditions, workflow_id, thread_id,
                     status, stage, view_version, write_allowed)
                VALUES (:id, :owner, :plan, :generation, :revision, 1,
                        CAST(:conditions AS jsonb), :workflow, :thread,
                        'acceptance_pending', '等待受理確認', 1, true)
            """),
                dict(
                    id=task_id,
                    owner=owner,
                    plan=plan_id,
                    generation=generation,
                    revision=revision,
                    conditions=plan.conditions.canonical_json(),
                    workflow=workflow_id,
                    thread=thread_id,
                ),
            )
            connection.execute(
                text("""
                INSERT INTO research_commands
                    (id, owner_id, generation, scope, key, payload_hash,
                     task_id, status)
                VALUES (:id, :owner, :generation, 'research.start', :key, :hash,
                        :task, 'acceptance_pending')
            """),
                dict(
                    id=command_id,
                    owner=owner,
                    generation=generation,
                    key=key,
                    hash=digest,
                    task=task_id,
                ),
            )
            return StartReceipt(command_id, task_id, workflow_id, "acceptance_pending")

    def confirm(
        self, owner: UUID, generation: int, command_id: UUID, run_id: str
    ) -> StartReceipt:
        if not run_id:
            raise ValueError("Temporal acceptance requires a run ID")
        with self.engine.begin() as connection:
            self._identity(connection, owner, generation)
            row = self._receipt(connection, owner, identifier=command_id)
            if row is None:
                raise ResearchConflict("NOT_FOUND")
            if row["generation"] != generation:
                raise ResearchConflict("IDENTITY_CHANGED")
            if row["status"] == "accepted":
                return self._view(row)
            plan = locked_plan(connection, row["plan_id"], owner)
            if plan is None or plan.generation != generation:
                raise ResearchConflict("NOT_FOUND")
            if plan.conditions_revision != row["conditions_revision"]:
                raise ResearchConflict("REVISION_CONFLICT")
            if not row["write_allowed"]:
                raise ResearchConflict("TASK_NOT_WRITABLE")
            changed = connection.execute(
                text("""
                UPDATE research_tasks SET temporal_run_id = :run,
                    status = CASE WHEN status = 'acceptance_pending'
                                  THEN 'queued' ELSE status END,
                    stage = CASE WHEN status = 'acceptance_pending'
                                 THEN '等待執行' ELSE stage END,
                    view_version = view_version +
                        CASE WHEN status = 'acceptance_pending' THEN 1 ELSE 0 END,
                    updated_at = now()
                WHERE id = :id AND owner_id = :owner AND write_allowed
                    AND generation = :generation
                RETURNING id
            """),
                dict(run=run_id, id=row["task_id"], owner=owner, generation=generation),
            ).scalar()
            if changed is None:
                raise ResearchConflict("TASK_NOT_WRITABLE")
            return self._save_acceptance(connection, row, run_id)

    def task(self, identifier: UUID, owner: UUID) -> TaskView | None:
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            row = (
                connection.execute(
                    text("""
                SELECT * FROM research_tasks
                WHERE id = :id AND owner_id = :owner AND generation = :generation
            """),
                    dict(id=identifier, owner=owner, generation=generation),
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return TaskView.model_validate(
                dict(
                    task_id=row["id"],
                    thread_id=row["thread_id"],
                    conditions_revision=row["conditions_revision"],
                    view_version=row["view_version"],
                    status=row["status"],
                    stage=row["stage"],
                    question=row["question"],
                    report_id=row["report_id"],
                    error=row["error"],
                    observed_at=datetime.now(UTC),
                )
            )

    @staticmethod
    def _identity(connection: Connection, owner: UUID, generation: int) -> None:
        if actor_generation(connection, owner, lock=True) != generation:
            raise ResearchConflict("IDENTITY_CHANGED")

    @staticmethod
    def _receipt(
        connection: Connection,
        owner: UUID,
        *,
        key: str | None = None,
        identifier: UUID | None = None,
    ) -> RowMapping | None:
        predicate = "c.key = :key" if key is not None else "c.id = :id"
        return (
            connection.execute(
                text(
                    """
            SELECT c.*, t.workflow_id, t.plan_id, t.conditions_revision,
                t.write_allowed, t.status AS task_status, t.temporal_run_id
            FROM research_commands c JOIN research_tasks t
                ON t.id = c.task_id AND t.owner_id = c.owner_id
            WHERE c.owner_id = :owner AND c.scope = 'research.start' AND
        """
                    + predicate
                ),
                dict(owner=owner, key=key, id=identifier),
            )
            .mappings()
            .first()
        )

    @staticmethod
    def _save_acceptance(
        connection: Connection, row: RowMapping, run_id: str | None
    ) -> StartReceipt:
        connection.execute(
            text("""
                UPDATE research_commands SET status = 'accepted',
                    result = CAST(:result AS jsonb), updated_at = now()
                WHERE id = :id AND owner_id = :owner
            """),
            dict(
                id=row["id"],
                owner=row["owner_id"],
                result=json.dumps(
                    dict(
                        task_id=str(row["task_id"]),
                        workflow_id=row["workflow_id"],
                        temporal_run_id=run_id,
                    )
                ),
            ),
        )
        return StartReceipt(row["id"], row["task_id"], row["workflow_id"], "accepted")

    @staticmethod
    def _view(row: RowMapping) -> StartReceipt:
        return StartReceipt(
            row["id"],
            row["task_id"],
            row["workflow_id"],
            cast(Literal["acceptance_pending", "accepted"], row["status"]),
        )
