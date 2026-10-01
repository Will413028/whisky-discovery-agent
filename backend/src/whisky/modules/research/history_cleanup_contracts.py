"""Opaque, bounded activity results used by the history cleanup Workflow."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HistoryCleanupPage:
    workflow_ids: tuple[str, ...]
    cursor: str | None
