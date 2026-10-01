"""A fenced, versioned snapshot for a single durable research execution."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Connection, Engine, text

from whisky.modules.catalog.public import price_policy_version, taiwan_date
from whisky.modules.discovery.public import locked_plan
from whisky.modules.identity.public import actor_generation
from whisky.modules.research.agent import PROMPT_VERSION
from whisky.modules.research.contracts import ResearchRunContext
from whisky.modules.research.contracts_v4 import ResearchExecutionV4
from whisky.modules.research.inputs_v4 import ResearchInputV4
from whisky.modules.research.store import ResearchConflict


class ResearchRunStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def begin_v4(self, task_id: UUID, prompt_version: str) -> ResearchExecutionV4:
        with self.engine.begin() as connection:
            context = self._begin(connection, task_id)
            value = connection.scalar(
                text(
                    "SELECT input FROM research_v4_inputs "
                    "WHERE task_id=:task AND owner_id=:owner"
                ),
                dict(task=task_id, owner=context.owner_id),
            )
            if value is None:
                raise ResearchConflict("V4_INPUT_NOT_FOUND")
            return ResearchExecutionV4(
                replace(context, prompt_version=prompt_version),
                ResearchInputV4.model_validate(value),
            )

    def begin(self, task_id: UUID) -> ResearchRunContext:
        with self.engine.begin() as connection:
            return self._begin(connection, task_id)

    @staticmethod
    def _begin(connection: Connection, task_id: UUID) -> ResearchRunContext:
        preliminary = connection.execute(
            text("SELECT owner_id,plan_id,generation FROM research_tasks WHERE id=:id"),
            {"id": task_id},
        ).first()
        if preliminary is None:
            raise ResearchConflict("NOT_FOUND")
        owner = preliminary.owner_id
        if actor_generation(connection, owner, lock=True) != preliminary.generation:
            raise ResearchConflict("IDENTITY_CHANGED")
        plan = locked_plan(connection, preliminary.plan_id, owner)
        if plan is None:
            raise ResearchConflict("NOT_FOUND")
        task = (
            connection.execute(
                text("SELECT * FROM research_tasks WHERE id=:id FOR UPDATE"),
                {"id": task_id},
            )
            .mappings()
            .one()
        )
        if (
            task["generation"] != preliminary.generation
            or task["conditions_revision"] != plan.conditions_revision
            or plan.generation != task["generation"]
            or not task["write_allowed"]
            or task["status"] not in {"acceptance_pending", "queued", "researching"}
        ):
            raise ResearchConflict("TASK_NOT_WRITABLE")
        if task["status"] != "researching":
            connection.execute(
                text("""
                    UPDATE research_tasks
                    SET status='researching',stage='查詢 reviewed catalog',
                        view_version=view_version+1,updated_at=now()
                    WHERE id=:id
                """),
                {"id": task_id},
            )
        return ResearchRunContext(
            task_id,
            owner,
            task["generation"],
            task["conditions_revision"],
            plan.conditions,
            taiwan_date(datetime.now(UTC)),
            price_policy_version(),
            PROMPT_VERSION,
        )

    def fail(self, context: ResearchRunContext) -> bool:
        """Publish a terminal error only while the original task fence still owns it."""
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
            changed = connection.execute(
                text("""
                UPDATE research_tasks
                SET status='failed',stage='研究未完成',
                    error=CAST(:error AS jsonb),
                    view_version=view_version+1,updated_at=now()
                WHERE id=:task AND owner_id=:owner AND generation=:generation
                  AND conditions_revision=:revision AND write_allowed
                  AND status='researching' AND report_id IS NULL
                RETURNING id
                """),
                dict(
                    task=context.task_id,
                    owner=context.owner_id,
                    generation=context.generation,
                    revision=context.conditions_revision,
                    error=json.dumps(
                        {
                            "code": "RESEARCH_FAILED",
                            "message": "研究未完成，請重新委託。",
                            "retryable": False,
                        },
                        ensure_ascii=False,
                    ),
                ),
            ).scalar()
            if changed is not None:
                connection.execute(
                    text("""
                    UPDATE agent_turns SET outcome=CAST(:outcome AS jsonb)
                    WHERE task_id=:task AND owner_id=:owner AND outcome IS NULL
                    """),
                    dict(
                        task=context.task_id,
                        owner=context.owner_id,
                        outcome=json.dumps(
                            {"type": "error", "code": "RESEARCH_FAILED"}
                        ),
                    ),
                )
            return changed is not None
