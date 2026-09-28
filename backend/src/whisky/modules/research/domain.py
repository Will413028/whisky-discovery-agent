"""Stable product identifiers independent of the workflow runtime."""

from uuid import UUID


def workflow_id_for(task_id: UUID) -> str:
    return f"whisky-research-{task_id}"
