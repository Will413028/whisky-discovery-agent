"""Versioned payloads crossing the Temporal workflow/activity boundary."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from whisky.modules.discovery.public import ResearchConditions
from whisky.modules.research.decision import ClarificationDraft
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
    clarification_id: UUID | None = None
    selected_version_id: UUID | None = None


@dataclass(frozen=True)
class QuestionCommit:
    context: ResearchRunContext
    waiting_version: int
    draft: ClarificationDraft
    expires_at: datetime


@dataclass(frozen=True)
class QuestionExpiry:
    context: ResearchRunContext
    question_id: UUID
    waiting_version: int
    at: datetime


@dataclass(frozen=True)
class PublishedQuestion:
    id: UUID
    task_id: UUID
    waiting_version: int
    expires_at: datetime


@dataclass(frozen=True)
class AnswerReceipt:
    id: UUID
    owner_id: UUID
    generation: int
    task_id: UUID
    question_id: UUID
    waiting_version: int
    conditions_revision: int
    answer: str
    acceptance: Literal["acceptance_pending", "accepted", "rejected"]
    code: str | None = None


@dataclass(frozen=True)
class AnswerResult:
    acceptance: Literal["accepted", "rejected"]
    code: str | None = None


@dataclass(frozen=True)
class AnswerInput:
    task_id: UUID
    question_id: UUID
    waiting_version: int
    conditions_revision: int
    key: str
    answer: str
    thread_id: UUID | None = None
    run_id: UUID | None = None
