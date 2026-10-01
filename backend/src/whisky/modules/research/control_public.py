"""Product task fences callable by the cross-module control transaction."""

import json
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Connection, text

from whisky.modules.research.domain import workflow_id_for
from whisky.platform.domain_errors import DomainRejection


def task_plan(connection: Connection, task_id: UUID, owner: UUID) -> UUID | None:
    """Read the parent before locking it; the caller rechecks under task lock."""
    return connection.execute(
        text("SELECT plan_id FROM research_tasks WHERE id=:task AND owner_id=:owner"),
        dict(task=task_id, owner=owner),
    ).scalar()


def cancel_task(
    connection: Connection, task_id: UUID, owner: UUID, generation: int, plan_id: UUID
) -> None:
    """Caller holds identity and plan locks before acquiring the task lock."""
    row = (
        connection.execute(
            text("""
            SELECT plan_id,generation,status,write_allowed FROM research_tasks
            WHERE id=:task AND owner_id=:owner FOR UPDATE
            """),
            dict(task=task_id, owner=owner),
        )
        .mappings()
        .first()
    )
    if row is None or row["plan_id"] != plan_id or row["generation"] != generation:
        raise DomainRejection("NOT_FOUND")
    if not row["write_allowed"] or row["status"] not in {
        "acceptance_pending",
        "queued",
        "researching",
        "needs_input",
    }:
        raise DomainRejection("TASK_TERMINAL")
    connection.execute(
        text("""
        UPDATE research_tasks SET status='cancelled', stage='研究已取消',
            write_allowed=false, question=NULL, active_question_id=NULL,
            view_version=view_version+1, updated_at=now()
        WHERE id=:task AND owner_id=:owner
        """),
        dict(task=task_id, owner=owner),
    )
    _close_questions_and_turns(
        connection, owner, "id=:task", dict(task=task_id), "TASK_CANCELLED"
    )


def close_plan_tasks(
    connection: Connection,
    owner: UUID,
    plan_id: UUID,
    *,
    status: str,
    newer_revision: int | None = None,
) -> None:
    """Close every still-writable child; completed reports remain historical."""
    if status not in {"cancelled", "superseded"}:
        raise ValueError("Invalid control task status")
    revision_clause = (
        "AND conditions_revision < :revision" if newer_revision is not None else ""
    )
    parameters = dict(owner=owner, plan=plan_id, revision=newer_revision)
    connection.execute(
        text(
            """
        UPDATE research_tasks SET status=:status, stage=:stage,
            write_allowed=false, question=NULL, active_question_id=NULL,
            view_version=view_version+1, updated_at=now()
        WHERE owner_id=:owner AND plan_id=:plan AND write_allowed
          AND status IN ('acceptance_pending','queued','researching','needs_input')
        """
            + revision_clause
        ),
        dict(
            **parameters,
            status=status,
            stage="研究條件已更新" if status == "superseded" else "研究已取消",
        ),
    )
    connection.execute(
        text(
            """
            UPDATE research_tasks SET write_allowed=false,
                view_version=view_version+1,updated_at=now()
            WHERE owner_id=:owner AND plan_id=:plan AND write_allowed
            """
            + revision_clause
        ),
        parameters,
    )
    condition = "plan_id=:plan AND status=:status"
    if newer_revision is not None:
        condition += " AND conditions_revision < :revision"
    _close_questions_and_turns(
        connection,
        owner,
        condition,
        dict(**parameters, status=status),
        "TASK_SUPERSEDED" if status == "superseded" else "TASK_CANCELLED",
    )


def close_actor_tasks(connection: Connection, owner: UUID, generation: int) -> None:
    """Fence descendants of the deleted identity generation."""
    connection.execute(
        text("""
        UPDATE research_tasks SET status='cancelled', stage='研究已取消',
            write_allowed=false, question=NULL, active_question_id=NULL,
            view_version=view_version+1, updated_at=now()
        WHERE owner_id=:owner AND generation<=:generation AND write_allowed
          AND status IN ('acceptance_pending','queued','researching','needs_input')
        """),
        dict(owner=owner, generation=generation),
    )
    connection.execute(
        text("""
            UPDATE research_tasks SET write_allowed=false,
                view_version=view_version+1,updated_at=now()
            WHERE owner_id=:owner AND generation<=:generation AND write_allowed
        """),
        dict(owner=owner, generation=generation),
    )
    _close_questions_and_turns(
        connection,
        owner,
        "generation<=:generation AND status='cancelled'",
        dict(generation=generation),
        "TASK_CANCELLED",
    )


def controlled_workflow_ids(
    connection: Connection,
    owner: UUID,
    kind: str,
    target: UUID,
    generation: int,
    expected_revision: int,
) -> tuple[str, ...]:
    """Only now-fenced, unfinished tasks require cooperative cancellation."""
    if kind == "task.cancel":
        condition = "id=:target AND status='cancelled'"
    elif kind == "plan.change_conditions":
        condition = (
            "plan_id=:target AND status='superseded' AND conditions_revision<=:revision"
        )
    elif kind == "plan.delete":
        condition = "plan_id=:target AND status='cancelled'"
    elif kind == "actor.delete":
        condition = "generation<=:generation AND status='cancelled'"
    else:
        raise ValueError("Unknown control kind")
    rows: Sequence[UUID] = (
        connection.execute(
            text(
                "SELECT id FROM research_tasks WHERE owner_id=:owner "
                f"AND {condition} ORDER BY id"
            ),
            dict(
                owner=owner,
                target=target,
                generation=generation,
                revision=expected_revision,
            ),
        )
        .scalars()
        .all()
    )
    return tuple(workflow_id_for(task_id) for task_id in rows)


def actor_tasks_closed(connection: Connection, owner: UUID, generation: int) -> bool:
    """Recovery fence for a removed identity generation."""
    return (
        connection.scalar(
            text("""
        SELECT count(*) FROM research_tasks
        WHERE owner_id=:owner AND generation=:generation AND write_allowed
        """),
            dict(owner=owner, generation=generation),
        )
        == 0
    )


def task_control_effect_present(
    connection: Connection, task_id: UUID, owner: UUID, generation: int
) -> bool:
    """Recovery read of one cancellation fence."""
    row = (
        connection.execute(
            text("""
            SELECT owner_id,generation,status,write_allowed
            FROM research_tasks WHERE id=:id
            """),
            dict(id=task_id),
        )
        .mappings()
        .first()
    )
    if row is None:
        return True
    if row["owner_id"] != owner or row["generation"] != generation:
        raise ValueError("control target belongs to another scope")
    return row["status"] in {"cancelled", "superseded"} and not row["write_allowed"]


def plan_tasks_closed(
    connection: Connection,
    plan_id: UUID,
    owner: UUID,
    generation: int,
    expected_revision: int | None,
) -> bool:
    """Recovery read of every task invalidated by a plan control effect."""
    revision_clause = (
        "AND conditions_revision<=:revision" if expected_revision is not None else ""
    )
    return (
        connection.scalar(
            text(
                """
        SELECT count(*) FROM research_tasks
        WHERE owner_id=:owner AND plan_id=:plan AND generation=:generation
          AND write_allowed
        """
                + revision_clause
            ),
            dict(
                owner=owner,
                plan=plan_id,
                generation=generation,
                revision=expected_revision,
            ),
        )
        == 0
    )


def _close_questions_and_turns(
    connection: Connection,
    owner: UUID,
    task_filter: str,
    parameters: dict[str, object],
    code: str,
) -> None:
    task_query = (
        f"SELECT id FROM research_tasks WHERE owner_id=:owner AND {task_filter}"
    )
    values = {**parameters, "owner": owner}
    connection.execute(
        text(
            "UPDATE clarifications SET status='closed' "
            "WHERE status='pending' AND owner_id=:owner "
            f"AND task_id IN ({task_query})"
        ),
        values,
    )
    connection.execute(
        text(
            "UPDATE agent_turns SET outcome=CAST(:outcome AS jsonb) "
            "WHERE (outcome IS NULL OR outcome->>'type'='interrupt') "
            "AND owner_id=:owner "
            f"AND task_id IN ({task_query})"
        ),
        dict(**values, outcome=json.dumps({"type": "error", "code": code})),
    )
