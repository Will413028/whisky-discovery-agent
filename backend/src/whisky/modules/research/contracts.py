"""Versioned payloads crossing the Temporal workflow/activity boundary."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from whisky.modules.discovery.public import ResearchConditions
from whisky.modules.research.decision import ClarificationDraft
from whisky.modules.research.report import ReportClaim, ReportDraft


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
class ResearchCatalogItem:
    index: int
    release_id: UUID
    item_id: UUID
    bottle_version_id: UUID
    name: str
    official_name: str
    version_label: str
    tasting_notes: str
    flavor_tags: tuple[str, ...]
    eligible: bool
    price_upper_bound_twd: str | None
    price_ids: tuple[UUID, ...]
    claims: tuple[ReportClaim, ...]


@dataclass(frozen=True)
class ResearchSourceOption:
    index: int
    item_index: int
    release_id: UUID
    bottle_version_id: UUID
    evidence_id: UUID
    publisher: str


@dataclass(frozen=True)
class ResearchCatalogSnapshot:
    release_id: UUID | None
    items: tuple[ResearchCatalogItem, ...]
    sources: tuple[ResearchSourceOption, ...]


@dataclass(frozen=True)
class SourceObservation:
    status: Literal["ok", "unavailable"]
    code: str | None = None
    text: str | None = None
    checked_on: date | None = None
    final_url: str | None = None


@dataclass(frozen=True)
class SourceObservationReceipt:
    status: Literal["ok", "unavailable"]
    code: str | None = None
    id: UUID | None = None
    content_sha256: str | None = None
    checked_on: date | None = None


@dataclass(frozen=True)
class ReadSourceRequest:
    context: ResearchRunContext
    source: ResearchSourceOption


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
    source_observation_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class QuestionCommit:
    context: ResearchRunContext
    waiting_version: int
    draft: ClarificationDraft
    expires_at: datetime


@dataclass(frozen=True)
class ReviewedVersionQuestionCommit:
    context: ResearchRunContext
    waiting_version: int
    release_id: UUID
    version_ids: tuple[UUID, ...]
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
