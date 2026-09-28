"""Versioned research report content, independent of storage and workflow runtime."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ReportClaim:
    kind: str
    key: str
    value: str
    evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class ReportCandidate:
    release_id: UUID
    item_id: UUID
    claims: tuple[ReportClaim, ...]
    reason: str
    price_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class ReportDraft:
    summary: str
    candidates: tuple[ReportCandidate, ...]
    unresolved: tuple[str, ...] = ()
