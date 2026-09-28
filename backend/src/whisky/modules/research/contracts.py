"""Versioned payloads crossing the Temporal workflow/activity boundary."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from whisky.modules.discovery.public import ResearchConditions
from whisky.modules.research.report import ReportDraft


@dataclass(frozen=True)
class ResearchRunContext:
    task_id: UUID
    owner_id: UUID
    generation: int
    conditions_revision: int
    conditions: ResearchConditions
    as_of: date
    policy_version: str
    prompt_version: str


@dataclass(frozen=True)
class ReportCommit:
    task_id: UUID
    owner_id: UUID
    generation: int
    artifact_key: str
    draft: ReportDraft
    policy_version: str
    prompt_version: str
    model_version: str
