"""Versioned public projections, independent of the execution mechanism."""

from datetime import date
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

STATUS_PAYLOADS = (
    ("needs_input", "question"),
    ("completed", "report_id"),
    ("failed", "error"),
)


def status_schema(schema: dict[str, Any]) -> None:
    """Expose the same cross-field rules to generated runtime validators."""
    schema["allOf"] = [
        {
            "if": {"properties": {"status": {"const": status}}},
            "then": {"properties": {to_camel(field): {"not": {"type": "null"}}}},
            "else": {"properties": {to_camel(field): {"type": "null"}}},
        }
        for status, field in STATUS_PAYLOADS
    ]


class ViewModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )


class QuestionChoiceView(ViewModel):
    id: UUID
    label: str = Field(min_length=1, max_length=160)


class QuestionView(ViewModel):
    id: UUID
    prompt: str = Field(min_length=1, max_length=2000)
    waiting_version: int = Field(ge=1)
    expires_at: AwareDatetime
    choices: tuple[QuestionChoiceView, ...] = ()


class ResearchCommandView(ViewModel):
    id: UUID
    task_id: UUID
    scope: Literal["research.start", "research.answer"] = "research.start"
    acceptance: Literal["acceptance_pending", "accepted", "rejected"]
    code: str | None = None


class TaskError(ViewModel):
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    retryable: bool


class TaskView(ViewModel):
    model_config = ConfigDict(json_schema_extra=status_schema)
    schema_version: Literal[1] = 1
    task_id: UUID
    thread_id: UUID
    conditions_revision: int = Field(ge=1)
    view_version: int = Field(ge=1)
    status: Literal[
        "acceptance_pending",
        "queued",
        "researching",
        "needs_input",
        "completed",
        "failed",
        "cancelled",
        "superseded",
    ]
    stage: str = Field(min_length=1, max_length=160)
    question: QuestionView | None
    report_id: UUID | None
    error: TaskError | None
    observed_at: AwareDatetime
    active_run_id: UUID | None = None

    @model_validator(mode="after")
    def status_payload(self) -> Self:
        for status, field in STATUS_PAYLOADS:
            if (self.status == status) != (getattr(self, field) is not None):
                raise ValueError(f"{status} requires exactly its matching payload")
        return self


class TaskHistoryItem(ViewModel):
    task: TaskView
    created_at: AwareDatetime


class TaskHistoryView(ViewModel):
    items: tuple[TaskHistoryItem, ...]
    next_cursor: str | None


class ReportSourceView(ViewModel):
    evidence_id: UUID
    url: str
    publisher: str | None
    checked_on: date


class ReportClaimView(ViewModel):
    kind: Literal["fact", "tag"]
    key: str
    value: str
    sources: tuple[ReportSourceView, ...]


class ReportPriceView(ViewModel):
    id: UUID
    amount: Decimal | None
    currency: str
    market: str
    volume_ml: int | None
    checked_on: date | None
    source: ReportSourceView


class ReportCandidateView(ViewModel):
    release_id: UUID
    item_id: UUID
    bottle_version_id: UUID
    name: str
    reason: str
    claims: tuple[ReportClaimView, ...]
    prices: tuple[ReportPriceView, ...]


class ClarifiedBottleView(ViewModel):
    question_id: UUID
    bottle_version_id: UUID
    name: str
    reviewed_in_release: bool


class ReportSourceObservationView(ViewModel):
    id: UUID
    status: Literal["ok", "unavailable"]
    review_status: Literal["unreviewed"]
    url: str
    requested_url: str
    publisher: str | None
    source_checked_on: date
    observed_at: AwareDatetime
    excerpt: str | None
    error_code: str | None


class ReportView(ViewModel):
    schema_version: Literal[1]
    id: UUID
    task_id: UUID
    conditions_revision: int
    catalog_release_id: UUID | None
    evaluated_on: date
    policy_version: str
    prompt_version: str
    model_version: str
    summary: str
    unresolved: tuple[str, ...]
    clarified_bottle: ClarifiedBottleView | None = None
    candidates: tuple[ReportCandidateView, ...]
    source_observations: tuple[ReportSourceObservationView, ...] = ()
