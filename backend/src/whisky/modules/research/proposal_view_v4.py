"""A preference draft is visible only while its own question is active."""

from typing import Literal
from uuid import UUID

from sqlalchemy import Engine, text

from whisky.modules.discovery.public import (
    PreferenceProposal,
    owned_plan,
    preference_proposal_for_task,
)
from whisky.modules.identity.public import actor_generation
from whisky.modules.research.inputs_v4 import ResearchInputV4
from whisky.modules.research.views import ViewModel


class PreferenceProposalViewV4(ViewModel):
    schema_version: Literal[4] = 4
    task_id: UUID
    plan_id: UUID
    question_id: UUID
    conditions_revision: int
    waiting_version: int
    source_text: str
    proposal: PreferenceProposal


def read_preference_proposal_v4(
    engine: Engine, owner: UUID, task_id: UUID
) -> PreferenceProposalViewV4 | None:
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            generation = actor_generation(connection, owner)
            if generation is None:
                return None
            row = (
                connection.execute(
                    text("""
                    SELECT t.plan_id,t.conditions_revision,c.id AS question_id,
                           c.waiting_version,i.input
                    FROM research_tasks t
                    JOIN clarifications c
                        ON c.id=t.active_question_id AND c.task_id=t.id
                        AND c.owner_id=t.owner_id AND c.generation=t.generation
                        AND c.conditions_revision=t.conditions_revision
                    JOIN research_v4_inputs i
                        ON i.task_id=t.id AND i.owner_id=t.owner_id
                    WHERE t.id=:task AND t.owner_id=:owner
                        AND t.generation=:generation
                        AND t.status='needs_input' AND t.write_allowed
                        AND c.kind='preference_proposal' AND c.status='pending'
                        AND c.expires_at>now()
                """),
                    dict(task=task_id, owner=owner, generation=generation),
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            plan = owned_plan(connection, row["plan_id"], owner)
            if (
                plan is None
                or plan.generation != generation
                or plan.conditions_revision != row["conditions_revision"]
            ):
                return None
            request = ResearchInputV4.model_validate(row["input"])
            if request.phase != "proposal" or request.source_text is None:
                return None
            proposal = preference_proposal_for_task(
                connection, task_id, owner, generation, row["conditions_revision"]
            )
            if proposal is None:
                return None
            proposal.validate_source(request.source_text)
            return PreferenceProposalViewV4(
                task_id=task_id,
                plan_id=plan.id,
                question_id=row["question_id"],
                conditions_revision=row["conditions_revision"],
                waiting_version=row["waiting_version"],
                source_text=request.source_text,
                proposal=proposal,
            )
