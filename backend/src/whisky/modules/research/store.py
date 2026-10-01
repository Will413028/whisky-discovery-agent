"""Product-owned research acceptance receipts and task projections."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, text

from whisky.modules.discovery.public import locked_plan, owned_plan
from whisky.modules.identity.public import actor_generation
from whisky.modules.research.commands import StartTurn
from whisky.modules.research.domain import workflow_id_for
from whisky.modules.research.inputs_v4 import StartTurnV4
from whisky.modules.research.proposal_view_v4 import (
    PreferenceProposalViewV4,
    read_preference_proposal_v4,
)
from whisky.modules.research.views import ResearchCommandView, TaskHistoryItem, TaskView


class ResearchConflict(ValueError):
    pass


@dataclass(frozen=True)
class TaskHistoryCursor:
    created_at: datetime
    id: UUID


@dataclass(frozen=True)
class TaskHistoryPage:
    items: tuple[TaskHistoryItem, ...]
    next_cursor: TaskHistoryCursor | None


@dataclass(frozen=True)
class StartReceipt:
    id: UUID
    task_id: UUID
    workflow_id: str
    acceptance: Literal["acceptance_pending", "accepted"]


class ResearchStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def workflow_type_for_task(
        self, task_id: UUID
    ) -> Literal["ResearchWorkflowV3", "ResearchWorkflowV4"]:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("""
                    SELECT (i.task_id IS NOT NULL) AS is_v4,
                        t.owner_id,t.plan_id,t.generation,t.write_allowed,t.status
                    FROM research_tasks t
                    LEFT JOIN research_v4_inputs i
                        ON i.task_id=t.id AND i.owner_id=t.owner_id
                    WHERE t.id=:task
                """),
                    {"task": task_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ResearchConflict("NOT_FOUND")
            plan = owned_plan(connection, row["plan_id"], row["owner_id"])
            if (
                actor_generation(connection, row["owner_id"]) != row["generation"]
                or plan is None
                or plan.generation != row["generation"]
                or (not row["write_allowed"] and row["status"] != "completed")
            ):
                raise ResearchConflict("TASK_NOT_WRITABLE")
            return "ResearchWorkflowV4" if row["is_v4"] else "ResearchWorkflowV3"

    def preference_proposal(
        self, task_id: UUID, owner: UUID
    ) -> PreferenceProposalViewV4 | None:
        return read_preference_proposal_v4(self.engine, owner, task_id)

    def reserve_turn_v4(
        self, owner: UUID, generation: int, turn: StartTurnV4
    ) -> StartReceipt:
        return self._reserve_turn(owner, generation, turn)

    def reserve_turn(
        self, owner: UUID, generation: int, turn: StartTurn
    ) -> StartReceipt:
        return self._reserve_turn(owner, generation, turn)

    def _reserve_turn(
        self, owner: UUID, generation: int, turn: StartTurn | StartTurnV4
    ) -> StartReceipt:
        with self.engine.begin() as connection:
            self._identity(connection, owner, generation)
            existing = self._receipt(connection, owner, key=turn.command.key)
            bound_task = connection.execute(
                text(
                    "SELECT id FROM research_tasks "
                    "WHERE owner_id = :owner AND thread_id = :thread"
                ),
                dict(owner=owner, thread=turn.thread_id),
            ).scalar()
            if bound_task is not None and (
                existing is None or bound_task != existing["task_id"]
            ):
                raise ResearchConflict("TURN_CONFLICT")
            if existing is not None:
                prior = connection.execute(
                    text(
                        "SELECT thread_id, run_id FROM agent_turns "
                        "WHERE command_id = :command AND owner_id = :owner"
                    ),
                    dict(command=existing["id"], owner=owner),
                ).first()
                if prior is not None and (
                    prior.thread_id != turn.thread_id or prior.run_id != turn.run_id
                ):
                    raise ResearchConflict("TURN_CONFLICT")
            command = turn.command
            source_task_id = (
                turn.command.source_task_id if isinstance(turn, StartTurnV4) else None
            )
            if source_task_id is not None and existing is None:
                source = connection.execute(
                    text("""SELECT id FROM research_tasks
                        WHERE id=:source AND owner_id=:owner AND generation=:generation
                            AND plan_id=:plan AND status='completed'"""),
                    dict(
                        source=source_task_id,
                        owner=owner,
                        generation=generation,
                        plan=command.plan_id,
                    ),
                ).first()
                if source is None:
                    raise ResearchConflict("NOT_FOUND")
            receipt = self._reserve(
                connection,
                owner,
                generation,
                command.plan_id,
                command.conditions_revision,
                command.key,
                turn.thread_id,
                sha256(
                    json.dumps(
                        dict(
                            schema_version=4,
                            plan_id=str(command.plan_id),
                            revision=command.conditions_revision,
                            input=turn.command.input.model_dump(
                                mode="json", by_alias=True
                            ),
                            **(
                                {"source_task_id": str(source_task_id)}
                                if source_task_id is not None
                                else {}
                            ),
                        ),
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                if isinstance(turn, StartTurnV4)
                else None,
            )
            if isinstance(turn, StartTurnV4):
                connection.execute(
                    text("""
                    INSERT INTO research_v4_inputs
                        (task_id,owner_id,input,source_task_id)
                    VALUES (:task,:owner,CAST(:input AS jsonb),:source)
                    ON CONFLICT (task_id) DO NOTHING
                """),
                    dict(
                        task=receipt.task_id,
                        owner=owner,
                        source=source_task_id,
                        input=turn.command.input.model_dump_json(by_alias=True),
                    ),
                )
            actual_thread: UUID = connection.execute(
                text(
                    "SELECT thread_id FROM research_tasks "
                    "WHERE id = :task AND owner_id = :owner"
                ),
                dict(task=receipt.task_id, owner=owner),
            ).scalar_one()
            if actual_thread != turn.thread_id:
                raise ResearchConflict("TURN_CONFLICT")
            connection.execute(
                text("""INSERT INTO agent_turns
                        (owner_id, task_id, thread_id, run_id, command_id)
                        VALUES (:owner, :task, :thread, :run, :command)
                        ON CONFLICT (command_id) DO NOTHING"""),
                dict(
                    owner=owner,
                    task=receipt.task_id,
                    thread=turn.thread_id,
                    run=turn.run_id,
                    command=receipt.id,
                ),
            )
            return receipt

    def reserve(
        self, owner: UUID, generation: int, plan_id: UUID, revision: int, key: str
    ) -> StartReceipt:
        with self.engine.begin() as connection:
            self._identity(connection, owner, generation)
            return self._reserve(connection, owner, generation, plan_id, revision, key)

    def _reserve(
        self,
        connection: Connection,
        owner: UUID,
        generation: int,
        plan_id: UUID,
        revision: int,
        key: str,
        thread_id: UUID | None = None,
        payload_digest: str | None = None,
    ) -> StartReceipt:
        if not key.strip() or len(key) > 128 or revision < 1:
            raise ValueError("Invalid research command key or revision")
        digest = (
            payload_digest
            or sha256(
                json.dumps(
                    dict(plan_id=str(plan_id), revision=revision), sort_keys=True
                ).encode()
            ).hexdigest()
        )
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
        task_id, command_id = uuid4(), uuid4()
        thread_id = thread_id or uuid4()
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

    def observed_task(
        self, identifier: UUID, run_id: UUID, owner: UUID
    ) -> TaskView | None:
        with self.engine.connect() as connection:
            bound = connection.execute(
                text(
                    "SELECT 1 FROM agent_turns "
                    "WHERE task_id = :task AND run_id = :run AND owner_id = :owner"
                ),
                dict(task=identifier, run=run_id, owner=owner),
            ).first()
        if bound is None:
            return None
        return self.task(identifier, owner)

    def turn_outcome(self, identifier: UUID, run_id: UUID, owner: UUID) -> dict | None:
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            if generation is None:
                return None
            result = connection.execute(
                text("""
                SELECT a.outcome FROM agent_turns a
                JOIN research_tasks t
                  ON t.id=a.task_id AND t.owner_id=a.owner_id
                WHERE a.task_id=:task AND a.run_id=:run AND a.owner_id=:owner
                  AND t.generation=:generation
                """),
                dict(task=identifier, run=run_id, owner=owner, generation=generation),
            ).scalar()
            return result if isinstance(result, dict) else None

    def command(self, identifier: UUID, owner: UUID) -> ResearchCommandView | None:
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            row = (
                connection.execute(
                    text("""
                    SELECT c.* FROM research_commands c
                    JOIN research_tasks t
                      ON t.id=c.task_id AND t.owner_id=c.owner_id
                    WHERE c.id=:id AND c.owner_id=:owner
                      AND t.generation=:generation
                    """),
                    dict(id=identifier, owner=owner, generation=generation),
                )
                .mappings()
                .first()
            )
            if row is None or generation is None or row["generation"] != generation:
                return None
            return ResearchCommandView(
                id=row["id"],
                task_id=row["task_id"],
                scope=row["scope"],
                acceptance=row["status"],
                code=row["result"].get("code") if row["result"] else None,
            )

    def task(self, identifier: UUID, owner: UUID) -> TaskView | None:
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            row = (
                connection.execute(
                    text("""
                SELECT t.*, (
                    SELECT a.run_id FROM agent_turns a
                    WHERE a.task_id=t.id AND a.owner_id=t.owner_id AND a.outcome IS NULL
                    LIMIT 1
                ) AS active_run_id
                FROM research_tasks t
                WHERE t.id = :id AND t.owner_id = :owner AND t.generation = :generation
            """),
                    dict(id=identifier, owner=owner, generation=generation),
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return self._task_view(row)

    def list_open(self, owner: UUID) -> tuple[TaskView, ...]:
        """Recover unfinished owned work after a browser or response is lost."""
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            if generation is None:
                return ()
            rows = connection.execute(
                text("""
                SELECT t.*, (
                    SELECT a.run_id FROM agent_turns a
                    WHERE a.task_id=t.id AND a.owner_id=t.owner_id AND a.outcome IS NULL
                    LIMIT 1
                ) AS active_run_id
                FROM research_tasks t
                WHERE t.owner_id=:owner AND t.generation=:generation
                  AND t.status IN (
                    'acceptance_pending','queued','researching','needs_input'
                  )
                ORDER BY t.updated_at DESC, t.id DESC LIMIT 20
                """),
                dict(owner=owner, generation=generation),
            ).mappings()
            return tuple(self._task_view(row) for row in rows)

    def history(
        self,
        plan_id: UUID,
        owner: UUID,
        limit: int,
        cursor: TaskHistoryCursor | None = None,
    ) -> TaskHistoryPage | None:
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            plan = owned_plan(connection, plan_id, owner)
            if plan is None or generation is None or plan.generation != generation:
                return None
            predicate = (
                "AND (t.created_at,t.id)<(:created_at,:cursor_id)" if cursor else ""
            )
            rows = (
                connection.execute(
                    text(
                        """
                SELECT t.*, (
                    SELECT a.run_id FROM agent_turns a
                    WHERE a.task_id=t.id AND a.owner_id=t.owner_id AND a.outcome IS NULL
                    LIMIT 1
                ) AS active_run_id
                FROM research_tasks t
                WHERE t.plan_id=:plan AND t.owner_id=:owner AND t.generation=:generation
                """
                        + predicate
                        + " ORDER BY t.created_at DESC,t.id DESC LIMIT :limit"
                    ),
                    dict(
                        plan=plan_id,
                        owner=owner,
                        generation=generation,
                        limit=limit + 1,
                        created_at=cursor.created_at if cursor else None,
                        cursor_id=cursor.id if cursor else None,
                    ),
                )
                .mappings()
                .all()
            )
            visible = rows[:limit]
            return TaskHistoryPage(
                tuple(
                    TaskHistoryItem(
                        task=self._task_view(row), created_at=row["created_at"]
                    )
                    for row in visible
                ),
                TaskHistoryCursor(visible[-1]["created_at"], visible[-1]["id"])
                if len(rows) > limit
                else None,
            )

    @staticmethod
    def _task_view(row: RowMapping) -> TaskView:
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
                active_run_id=row["active_run_id"],
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
