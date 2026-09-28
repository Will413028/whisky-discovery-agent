"""Versioned public projections, independent of the execution mechanism."""

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


class QuestionView(ViewModel):
    id: UUID
    prompt: str = Field(min_length=1, max_length=2000)
    waiting_version: int = Field(ge=1)
    expires_at: AwareDatetime


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

    @model_validator(mode="after")
    def status_payload(self) -> Self:
        for status, field in STATUS_PAYLOADS:
            if (self.status == status) != (getattr(self, field) is not None):
                raise ValueError(f"{status} requires exactly its matching payload")
        return self
