"""Owned, versioned clarification state for a durable research task."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, text

from whisky.modules.catalog.public import (
    current_release_id,
    reviewed_version_in_release,
)
from whisky.modules.discovery.public import locked_plan
from whisky.modules.identity.public import actor_generation
from whisky.modules.research.contracts import (
    AnswerReceipt,
    AnswerResult,
    PublishedQuestion,
    ResearchRunContext,
)
from whisky.modules.research.decision import ClarificationDraft
from whisky.modules.research.store import ResearchConflict


class ClarificationStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def publish(
        self,
        context: ResearchRunContext,
        waiting_version: int,
        draft: ClarificationDraft,
        expires_at: datetime,
    ) -> PublishedQuestion:
        if (
            waiting_version < 1
            or not draft.prompt.strip()
            or len(draft.prompt) > 2000
            or not 2 <= len(draft.choices) <= 5
            or len(set(draft.choices)) != len(draft.choices)
            or any(not choice.strip() or len(choice) > 160 for choice in draft.choices)
            or expires_at.utcoffset() is None
        ):
            raise ValueError("Invalid clarification question")
        try:
            version_ids = tuple(UUID(choice) for choice in draft.choices)
        except ValueError:
            raise ValueError("INVALID_VERSION_CHOICE") from None
        if len(set(version_ids)) != len(version_ids):
            raise ValueError("INVALID_VERSION_CHOICE")
        return self._publish(
            context,
            waiting_version,
            version_ids,
            expires_at,
            lambda versions: draft.prompt,
        )

    def publish_reviewed_versions(
        self,
        context: ResearchRunContext,
        waiting_version: int,
        version_ids: tuple[UUID, ...],
        expires_at: datetime,
        release_id: UUID,
    ) -> PublishedQuestion:
        """V3 accepts only reviewed IDs; the DB resolves canonical labels."""
        return self._publish(
            context,
            waiting_version,
            version_ids,
            expires_at,
            self._reviewed_prompt,
            expected_release_id=release_id,
        )

    @staticmethod
    def _reviewed_prompt(versions: list[dict[str, str]]) -> str:
        return (
            "請確認您喝過的酒款版本：「"
            + "」、「".join(version["label"] for version in versions)
            + "」？"
        )

    def _publish(
        self,
        context: ResearchRunContext,
        waiting_version: int,
        version_ids: tuple[UUID, ...],
        expires_at: datetime,
        prompt_for: Callable[[list[dict[str, str]]], str],
        *,
        expected_release_id: UUID | None = None,
    ) -> PublishedQuestion:
        if (
            waiting_version < 1
            or not 2 <= len(version_ids) <= 5
            or len(set(version_ids)) != len(version_ids)
            or expires_at.utcoffset() is None
        ):
            raise ValueError("Invalid clarification question")
        with self.engine.begin() as connection:
            if (
                actor_generation(connection, context.owner_id, lock=True)
                != context.generation
            ):
                raise ResearchConflict("IDENTITY_CHANGED")
            preliminary = connection.execute(
                text("""
                SELECT plan_id FROM research_tasks
                WHERE id=:task AND owner_id=:owner
                """),
                dict(task=context.task_id, owner=context.owner_id),
            ).first()
            if preliminary is None:
                raise ResearchConflict("NOT_FOUND")
            plan = locked_plan(connection, preliminary.plan_id, context.owner_id)
            if plan is None or plan.conditions_revision != context.conditions_revision:
                raise ResearchConflict("REVISION_CONFLICT")
            task = connection.execute(
                text("""
                SELECT generation,conditions_revision,status,write_allowed
                FROM research_tasks WHERE id=:task AND owner_id=:owner FOR UPDATE
                """),
                dict(task=context.task_id, owner=context.owner_id),
            ).one()
            if (
                task.generation != context.generation
                or task.conditions_revision != context.conditions_revision
                or not task.write_allowed
            ):
                raise ResearchConflict("TASK_NOT_WRITABLE")
            existing = (
                connection.execute(
                    text("""
                SELECT * FROM clarifications
                WHERE task_id=:task AND waiting_version=:version
                """),
                    dict(task=context.task_id, version=waiting_version),
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if (
                    existing["prompt"] != prompt_for(existing["choices"])
                    or tuple(UUID(choice["id"]) for choice in existing["choices"])
                    != version_ids
                    or existing["expires_at"] != expires_at
                ):
                    raise ResearchConflict("QUESTION_EXISTS")
                return PublishedQuestion(
                    existing["id"], context.task_id, waiting_version, expires_at
                )
            if expires_at <= datetime.now(UTC):
                raise ValueError("Invalid clarification question")
            if task.status != "researching":
                raise ResearchConflict("TASK_NOT_WRITABLE")
            release_id = current_release_id(connection)
            if expected_release_id is not None and release_id != expected_release_id:
                raise ResearchConflict("CATALOG_CHANGED")
            versions = []
            for version_id in version_ids:
                version = (
                    reviewed_version_in_release(connection, release_id, version_id)
                    if release_id is not None
                    else None
                )
                if version is None:
                    raise ValueError("INVALID_VERSION_CHOICE")
                versions.append({"id": str(version_id), "label": version.name})
            prompt = prompt_for(versions)
            if not prompt.strip() or len(prompt) > 2000:
                raise ValueError("Invalid clarification question")
            question_id = uuid4()
            connection.execute(
                text("""
                INSERT INTO clarifications
                    (id,task_id,owner_id,generation,conditions_revision,
                     waiting_version,prompt,choices,status,expires_at)
                VALUES (:id,:task,:owner,:generation,:revision,:version,
                        :prompt,CAST(:choices AS jsonb),'pending',:expires)
                """),
                dict(
                    id=question_id,
                    task=context.task_id,
                    owner=context.owner_id,
                    generation=context.generation,
                    revision=context.conditions_revision,
                    version=waiting_version,
                    prompt=prompt,
                    choices=json.dumps(versions, ensure_ascii=False),
                    expires=expires_at,
                ),
            )
            question_view = dict(
                id=str(question_id),
                prompt=prompt,
                waitingVersion=waiting_version,
                expiresAt=expires_at.isoformat(),
                choices=versions,
            )
            connection.execute(
                text("""
                UPDATE agent_turns SET outcome=CAST(:outcome AS jsonb)
                WHERE task_id=:task AND owner_id=:owner AND outcome IS NULL
                """),
                dict(
                    task=context.task_id,
                    owner=context.owner_id,
                    outcome=json.dumps(
                        {"type": "interrupt", "question": question_view},
                        ensure_ascii=False,
                    ),
                ),
            )
            connection.execute(
                text("""
                UPDATE research_tasks
                SET status='needs_input',stage='等待版本補充',
                    active_question_id=:question,question=CAST(:view AS jsonb),
                    view_version=view_version+1,updated_at=now()
                WHERE id=:task AND owner_id=:owner
                """),
                dict(
                    question=question_id,
                    task=context.task_id,
                    owner=context.owner_id,
                    view=json.dumps(question_view, ensure_ascii=False),
                ),
            )
            return PublishedQuestion(
                question_id, context.task_id, waiting_version, expires_at
            )

    def reserve_answer(
        self,
        owner: UUID,
        generation: int,
        task_id: UUID,
        question_id: UUID,
        waiting_version: int,
        conditions_revision: int,
        key: str,
        answer: str,
        *,
        thread_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> AnswerReceipt:
        if (
            not key.strip()
            or len(key) > 128
            or not answer.strip()
            or len(answer) > 160
            or waiting_version < 1
            or conditions_revision < 1
            or ((thread_id is None) != (run_id is None))
        ):
            raise ValueError("Invalid answer command")
        digest = self._answer_hash(
            task_id, question_id, waiting_version, conditions_revision, answer
        )
        with self.engine.begin() as connection:
            if actor_generation(connection, owner, lock=True) != generation:
                raise ResearchConflict("IDENTITY_CHANGED")
            preliminary = connection.execute(
                text("""
                SELECT plan_id FROM research_tasks
                WHERE id=:task AND owner_id=:owner
                """),
                dict(task=task_id, owner=owner),
            ).first()
            if preliminary is None:
                raise ResearchConflict("NOT_FOUND")
            plan = locked_plan(connection, preliminary.plan_id, owner)
            if plan is None or plan.generation != generation:
                raise ResearchConflict("NOT_FOUND")
            task = (
                connection.execute(
                    text("""
                SELECT * FROM research_tasks
                WHERE id=:task AND owner_id=:owner FOR UPDATE
                """),
                    dict(task=task_id, owner=owner),
                )
                .mappings()
                .one()
            )
            existing = (
                connection.execute(
                    text("""
                SELECT * FROM research_commands
                WHERE owner_id=:owner AND scope='research.answer' AND key=:key
                FOR UPDATE
                """),
                    dict(owner=owner, key=key),
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if existing["payload_hash"] != digest:
                    raise ResearchConflict("IDEMPOTENCY_CONFLICT")
                if existing["generation"] != generation:
                    raise ResearchConflict("IDENTITY_CHANGED")
                self._bind_turn(
                    connection, owner, task, existing["id"], thread_id, run_id
                )
                return self._answer_receipt(
                    existing["id"],
                    owner,
                    generation,
                    task_id,
                    question_id,
                    waiting_version,
                    conditions_revision,
                    answer,
                    existing["status"],
                    existing["result"].get("code") if existing["result"] else None,
                )
            if (
                task["generation"] != generation
                or task["conditions_revision"] != conditions_revision
                or plan.conditions_revision != conditions_revision
                or not task["write_allowed"]
            ):
                raise ResearchConflict("REVISION_CONFLICT")
            if (
                task["status"] != "needs_input"
                or task["active_question_id"] != question_id
            ):
                raise ResearchConflict("QUESTION_CLOSED")
            question = (
                connection.execute(
                    text("""
                SELECT * FROM clarifications
                WHERE id=:question AND task_id=:task AND owner_id=:owner
                FOR UPDATE
                """),
                    dict(question=question_id, task=task_id, owner=owner),
                )
                .mappings()
                .first()
            )
            if (
                question is None
                or question["waiting_version"] != waiting_version
                or question["status"] != "pending"
            ):
                raise ResearchConflict("QUESTION_CLOSED")
            if question["expires_at"] <= datetime.now(UTC):
                raise ResearchConflict("QUESTION_EXPIRED")
            if answer not in {choice["id"] for choice in question["choices"]}:
                raise ResearchConflict("INVALID_ANSWER")
            command_id = uuid4()
            connection.execute(
                text("""
                INSERT INTO research_commands
                    (id,owner_id,generation,scope,key,payload_hash,task_id,
                     question_id,waiting_version,status)
                VALUES (:id,:owner,:generation,'research.answer',:key,:hash,:task,
                        :question,:version,'acceptance_pending')
                """),
                dict(
                    id=command_id,
                    owner=owner,
                    generation=generation,
                    key=key,
                    hash=digest,
                    task=task_id,
                    question=question_id,
                    version=waiting_version,
                ),
            )
            self._bind_turn(connection, owner, task, command_id, thread_id, run_id)
            return self._answer_receipt(
                command_id,
                owner,
                generation,
                task_id,
                question_id,
                waiting_version,
                conditions_revision,
                answer,
                "acceptance_pending",
            )

    def accept_answer(self, receipt: AnswerReceipt) -> AnswerResult:
        with self.engine.begin() as connection:
            if (
                actor_generation(connection, receipt.owner_id, lock=True)
                != receipt.generation
            ):
                raise ResearchConflict("IDENTITY_CHANGED")
            preliminary = connection.execute(
                text("""
                SELECT plan_id FROM research_tasks
                WHERE id=:task AND owner_id=:owner
                """),
                dict(task=receipt.task_id, owner=receipt.owner_id),
            ).first()
            if preliminary is None:
                raise ResearchConflict("NOT_FOUND")
            plan = locked_plan(connection, preliminary.plan_id, receipt.owner_id)
            if plan is None or plan.generation != receipt.generation:
                raise ResearchConflict("NOT_FOUND")
            task = (
                connection.execute(
                    text("""
                SELECT * FROM research_tasks
                WHERE id=:task AND owner_id=:owner FOR UPDATE
                """),
                    dict(task=receipt.task_id, owner=receipt.owner_id),
                )
                .mappings()
                .one()
            )
            command = (
                connection.execute(
                    text("""
                SELECT * FROM research_commands
                WHERE id=:id AND owner_id=:owner AND scope='research.answer'
                FOR UPDATE
                """),
                    dict(id=receipt.id, owner=receipt.owner_id),
                )
                .mappings()
                .first()
            )
            if (
                command is None
                or command["task_id"] != receipt.task_id
                or command["question_id"] != receipt.question_id
                or command["waiting_version"] != receipt.waiting_version
                or command["generation"] != receipt.generation
                or command["payload_hash"]
                != self._answer_hash(
                    receipt.task_id,
                    receipt.question_id,
                    receipt.waiting_version,
                    receipt.conditions_revision,
                    receipt.answer,
                )
            ):
                raise ResearchConflict("IDEMPOTENCY_CONFLICT")
            if command["status"] == "accepted":
                return AnswerResult("accepted")
            if command["status"] == "rejected":
                return AnswerResult("rejected", command["result"]["code"])
            question = (
                connection.execute(
                    text("""
                SELECT * FROM clarifications
                WHERE id=:question AND task_id=:task AND owner_id=:owner
                FOR UPDATE
                """),
                    dict(
                        question=receipt.question_id,
                        task=receipt.task_id,
                        owner=receipt.owner_id,
                    ),
                )
                .mappings()
                .first()
            )
            code: str | None = None
            if (
                task["generation"] != receipt.generation
                or task["conditions_revision"] != receipt.conditions_revision
                or plan.conditions_revision != receipt.conditions_revision
                or not task["write_allowed"]
            ):
                code = "REVISION_CONFLICT"
            elif (
                question is None
                or question["status"] != "pending"
                or question["waiting_version"] != receipt.waiting_version
                or task["status"] != "needs_input"
                or task["active_question_id"] != receipt.question_id
            ):
                code = "QUESTION_CLOSED"
            elif question["expires_at"] <= datetime.now(UTC):
                code = "QUESTION_EXPIRED"
            elif receipt.answer not in {choice["id"] for choice in question["choices"]}:
                code = "INVALID_ANSWER"
            if code is not None:
                connection.execute(
                    text("""
                    UPDATE research_commands
                    SET status='rejected',result=CAST(:result AS jsonb),updated_at=now()
                    WHERE id=:id
                    """),
                    dict(id=receipt.id, result=json.dumps({"code": code})),
                )
                return AnswerResult("rejected", code)
            connection.execute(
                text("""
                UPDATE clarifications
                SET status='answered',answer=:answer,answer_command_id=:command,
                    answered_at=now()
                WHERE id=:question AND status='pending'
                """),
                dict(
                    answer=receipt.answer,
                    command=receipt.id,
                    question=receipt.question_id,
                ),
            )
            connection.execute(
                text("""
                UPDATE research_tasks
                SET status='researching',stage='重新查核 reviewed catalog',
                    question=NULL,active_question_id=NULL,
                    view_version=view_version+1,updated_at=now()
                WHERE id=:task AND owner_id=:owner
                """),
                dict(task=receipt.task_id, owner=receipt.owner_id),
            )
            connection.execute(
                text("""
                UPDATE research_commands
                SET status='accepted',result=CAST(:result AS jsonb),updated_at=now()
                WHERE id=:id
                """),
                dict(
                    id=receipt.id,
                    result=json.dumps(
                        {
                            "questionId": str(receipt.question_id),
                            "answer": receipt.answer,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            return AnswerResult("accepted")

    def expire(
        self,
        context: ResearchRunContext,
        question_id: UUID,
        waiting_version: int,
        at: datetime,
    ) -> bool:
        if at.utcoffset() is None:
            raise ValueError("Expiry check requires an aware time")
        with self.engine.begin() as connection:
            if (
                actor_generation(connection, context.owner_id, lock=True)
                != context.generation
            ):
                return False
            preliminary = connection.execute(
                text("""
                SELECT plan_id FROM research_tasks
                WHERE id=:task AND owner_id=:owner
                """),
                dict(task=context.task_id, owner=context.owner_id),
            ).first()
            if preliminary is None:
                return False
            plan = locked_plan(connection, preliminary.plan_id, context.owner_id)
            if plan is None or plan.conditions_revision != context.conditions_revision:
                return False
            task = (
                connection.execute(
                    text("""
                SELECT * FROM research_tasks
                WHERE id=:task AND owner_id=:owner FOR UPDATE
                """),
                    dict(task=context.task_id, owner=context.owner_id),
                )
                .mappings()
                .one()
            )
            if (
                task["generation"] != context.generation
                or task["conditions_revision"] != context.conditions_revision
                or task["status"] != "needs_input"
                or task["active_question_id"] != question_id
                or not task["write_allowed"]
            ):
                return False
            question = connection.execute(
                text("""
                SELECT status,waiting_version,expires_at FROM clarifications
                WHERE id=:question AND task_id=:task FOR UPDATE
                """),
                dict(question=question_id, task=context.task_id),
            ).first()
            if (
                question is None
                or question.status != "pending"
                or question.waiting_version != waiting_version
                or at < question.expires_at
            ):
                return False
            connection.execute(
                text("""
                UPDATE clarifications SET status='expired'
                WHERE id=:question AND status='pending'
                """),
                {"question": question_id},
            )
            connection.execute(
                text("""
                UPDATE research_commands
                SET status='rejected',result=CAST(:result AS jsonb),updated_at=now()
                WHERE question_id=:question AND task_id=:task
                  AND owner_id=:owner AND status='acceptance_pending'
                """),
                dict(
                    question=question_id,
                    task=context.task_id,
                    owner=context.owner_id,
                    result=json.dumps({"code": "QUESTION_EXPIRED"}),
                ),
            )
            connection.execute(
                text("""
                UPDATE research_tasks
                SET status='failed',stage='補充期限已過',
                    question=NULL,active_question_id=NULL,
                    error=CAST(:error AS jsonb),
                    view_version=view_version+1,updated_at=now()
                WHERE id=:task AND owner_id=:owner
                """),
                dict(
                    task=context.task_id,
                    owner=context.owner_id,
                    error=json.dumps(
                        {
                            "code": "INPUT_EXPIRED",
                            "message": "補充期限已過，請重新委託。",
                            "retryable": False,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            return True

    @staticmethod
    def _answer_hash(
        task_id: UUID,
        question_id: UUID,
        waiting_version: int,
        conditions_revision: int,
        answer: str,
    ) -> str:
        return sha256(
            json.dumps(
                dict(
                    task_id=str(task_id),
                    question_id=str(question_id),
                    waiting_version=waiting_version,
                    conditions_revision=conditions_revision,
                    answer=answer,
                ),
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()

    @staticmethod
    def _answer_receipt(
        identifier: UUID,
        owner: UUID,
        generation: int,
        task_id: UUID,
        question_id: UUID,
        waiting_version: int,
        conditions_revision: int,
        answer: str,
        status: Literal["acceptance_pending", "accepted", "rejected"],
        code: str | None = None,
    ) -> AnswerReceipt:
        return AnswerReceipt(
            identifier,
            owner,
            generation,
            task_id,
            question_id,
            waiting_version,
            conditions_revision,
            answer,
            status,
            code,
        )

    @staticmethod
    def _bind_turn(
        connection: Connection,
        owner: UUID,
        task: RowMapping,
        command_id: UUID,
        thread_id: UUID | None,
        run_id: UUID | None,
    ) -> None:
        if thread_id is None or run_id is None:
            return
        if task["thread_id"] != thread_id:
            raise ResearchConflict("TURN_CONFLICT")
        bound = connection.execute(
            text("""
            SELECT thread_id,run_id FROM agent_turns
            WHERE command_id=:command AND owner_id=:owner
            """),
            dict(command=command_id, owner=owner),
        ).first()
        if bound is not None:
            if bound.thread_id != thread_id or bound.run_id != run_id:
                raise ResearchConflict("TURN_CONFLICT")
            return
        open_turn = connection.execute(
            text("""
            SELECT run_id FROM agent_turns
            WHERE task_id=:task AND owner_id=:owner AND outcome IS NULL
            """),
            dict(task=task["id"], owner=owner),
        ).first()
        if open_turn is not None:
            raise ResearchConflict("TURN_CONFLICT")
        collision = connection.execute(
            text("""
            SELECT command_id FROM agent_turns
            WHERE owner_id=:owner AND thread_id=:thread AND run_id=:run
            """),
            dict(owner=owner, thread=thread_id, run=run_id),
        ).first()
        if collision is not None:
            raise ResearchConflict("TURN_CONFLICT")
        outcome = (
            {"type": "success", "reportId": str(task["report_id"])}
            if task["status"] == "completed"
            else None
        )
        connection.execute(
            text("""
            INSERT INTO agent_turns
                (owner_id,task_id,thread_id,run_id,command_id,outcome)
            VALUES (:owner,:task,:thread,:run,:command,CAST(:outcome AS jsonb))
            """),
            dict(
                owner=owner,
                task=task["id"],
                thread=thread_id,
                run=run_id,
                command=command_id,
                outcome=json.dumps(outcome) if outcome is not None else None,
            ),
        )
