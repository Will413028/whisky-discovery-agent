"""Stable product identifiers independent of the workflow runtime."""

from uuid import UUID


class ResearchConflict(ValueError):
    pass


def workflow_id_for(task_id: UUID) -> str:
    return f"whisky-research-{task_id}"
