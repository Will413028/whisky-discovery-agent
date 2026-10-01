"""Erase research originals beneath a locked deletion fence."""

from uuid import UUID

from sqlalchemy import Connection, text

from whisky.modules.discovery.public import locked_plan_deletion_fence
from whisky.modules.identity.public import control_actor_state


def purge_actor_research(connection: Connection, owner: UUID, generation: int) -> None:
    actor = control_actor_state(connection, owner, lock=True)
    if actor is not None and not (
        actor[0] > generation or actor == (generation, False)
    ):
        raise RuntimeError("research purge requires an advanced identity fence")
    _purge(
        connection, "generation<=:generation", dict(owner=owner, generation=generation)
    )


def purge_plan_research(
    connection: Connection, owner: UUID, generation: int, plan_id: UUID
) -> None:
    actor = control_actor_state(connection, owner, lock=True)
    if actor is not None and actor[0] < generation:
        raise RuntimeError("research purge generation is not current")
    if not locked_plan_deletion_fence(connection, plan_id, owner, generation):
        raise RuntimeError("research purge requires a deleted plan fence")
    _purge(
        connection,
        "generation<=:generation AND plan_id=:plan",
        dict(owner=owner, generation=generation, plan=plan_id),
    )


def _purge(connection: Connection, predicate: str, values: dict) -> None:
    tasks = "SELECT id FROM research_tasks WHERE owner_id=:owner AND " + predicate
    reports = "SELECT id FROM research_reports WHERE task_id IN (" + tasks + ")"
    connection.execute(
        text(
            "UPDATE research_tasks SET status='cancelled',stage='研究紀錄已刪除',"
            "conditions='{}'::jsonb,question=NULL,error=NULL,report_id=NULL,"
            "active_question_id=NULL,write_allowed=false,"
            "view_version=view_version+1,updated_at=now() "
            "WHERE owner_id=:owner AND " + predicate + " AND (conditions<>'{}'::jsonb "
            "OR status<>'cancelled' OR report_id IS NOT NULL OR question IS NOT NULL "
            "OR error IS NOT NULL OR active_question_id IS NOT NULL OR write_allowed)"
        ),
        values,
    )
    for table in (
        "research_report_citations",
        "research_report_prices",
        "research_report_claims",
        "research_report_candidates",
        "research_report_source_observations",
        "research_report_comparisons",
    ):
        connection.execute(
            text(f"DELETE FROM {table} WHERE report_id IN ({reports})"), values
        )
    connection.execute(
        text(f"DELETE FROM research_reports WHERE id IN ({reports})"), values
    )
    connection.execute(
        text(
            "UPDATE clarifications SET status='closed',answer=NULL,"
            "answer_command_id=NULL "
            f"WHERE task_id IN ({tasks})"
        ),
        values,
    )
    for table in (
        "agent_turns",
        "research_commands",
        "clarifications",
        "research_source_observations",
        "preference_proposals",
        "research_v4_inputs",
    ):
        connection.execute(
            text(f"DELETE FROM {table} WHERE task_id IN ({tasks})"), values
        )
    connection.execute(
        text(
            f"DELETE FROM research_usage_attempts WHERE task_id IN ({tasks}) "
            "AND status<>'active'"
        ),
        values,
    )
