"""An explicit historical direction is data for a new research, not current facts."""

from typing import Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import Engine, text

from whisky.modules.discovery.public import (
    CatalogReference,
    ExplorationIntent,
    owned_plan,
)
from whisky.modules.identity.public import actor_generation
from whisky.modules.research.inputs_v4 import ResearchInputV4
from whisky.modules.research.views import ViewModel


class RestartContextViewV4(ViewModel):
    schema_version: Literal[4] = 4
    plan_id: UUID
    task_id: UUID
    source_conditions_revision: int = Field(ge=1)
    source_starting_bottle: CatalogReference | None
    input: ResearchInputV4


def read_restart_context_v4(
    engine: Engine, owner: UUID, plan_id: UUID, task_id: UUID
) -> RestartContextViewV4 | None:
    with engine.connect() as connection:
        generation = actor_generation(connection, owner)
        if generation is None:
            return None
        plan = owned_plan(connection, plan_id, owner)
        if plan is None or plan.generation != generation:
            return None
        row = connection.execute(
            text("""
                SELECT t.conditions_revision,t.conditions,c.content->'intent' AS intent,
                    r.selected_version_id,r.selected_label,r.selected_item_id,
                    r.catalog_release_id
                FROM research_tasks t
                JOIN research_reports r ON r.id=t.report_id AND r.task_id=t.id
                    AND r.owner_id=t.owner_id AND r.generation=t.generation
                JOIN research_report_comparisons c ON c.report_id=r.id
                WHERE t.id=:task AND t.owner_id=:owner AND t.generation=:generation
                    AND t.plan_id=:plan AND t.status='completed'
            """),
            dict(task=task_id, owner=owner, generation=generation, plan=plan_id),
        ).first()
    if row is None:
        return None
    intent = ExplorationIntent.model_validate(row.intent)
    starting_bottle = (
        CatalogReference.model_validate(row.conditions["starting_bottle"])
        if row.conditions.get("starting_bottle") is not None
        else None
    )
    if row.selected_version_id is not None:
        intent = intent.model_copy(update={"origin_query": row.selected_label})
        starting_bottle = (
            CatalogReference(
                release_id=row.catalog_release_id, item_id=row.selected_item_id
            )
            if row.catalog_release_id is not None and row.selected_item_id is not None
            else None
        )
    return RestartContextViewV4(
        plan_id=plan_id,
        task_id=task_id,
        source_conditions_revision=row.conditions_revision,
        source_starting_bottle=starting_bottle,
        input=ResearchInputV4(phase="research", intent=intent),
    )
