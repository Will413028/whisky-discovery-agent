"""Allowlisted application commands extracted from untrusted AG-UI input."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from ag_ui.core import RunAgentInput
from pydantic import Field, field_validator

from whisky.modules.research.contracts import AnswerInput
from whisky.modules.research.views import ViewModel


class StartCommand(ViewModel):
    type: Literal["start"]
    key: str = Field(min_length=1, max_length=128)
    plan_id: UUID
    conditions_revision: int = Field(ge=1)

    @field_validator("key")
    @classmethod
    def nonblank_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Command key must not be blank")
        return value


@dataclass(frozen=True)
class StartTurn:
    thread_id: UUID
    run_id: UUID
    command: StartCommand


def parse_start(request: RunAgentInput) -> StartTurn:
    if request.resume or request.parent_run_id is not None:
        raise ValueError("Start cannot carry resume or parent-run semantics")
    return StartTurn(
        UUID(request.thread_id),
        UUID(request.run_id),
        StartCommand.model_validate(request.forwarded_props),
    )


@dataclass(frozen=True)
class AnswerTurn:
    thread_id: UUID
    run_id: UUID
    command: AnswerInput


class AnswerEnvelope(ViewModel):
    type: Literal["answer"]
    key: str = Field(min_length=1, max_length=128)
    task_id: UUID
    conditions_revision: int = Field(ge=1)
    waiting_version: int = Field(ge=1)

    @field_validator("key")
    @classmethod
    def nonblank_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Command key must not be blank")
        return value


def parse_resume(request: RunAgentInput) -> AnswerTurn:
    if not request.resume or len(request.resume) != 1:
        raise ValueError("Exactly one clarification is required")
    resume = request.resume[0]
    if resume.status != "resolved":
        raise ValueError("Cancelled clarification is not an answer")
    payload = resume.payload
    if not isinstance(payload, dict) or set(payload) != {"answer"}:
        raise ValueError("Clarification answer must be typed")
    answer = payload["answer"]
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 160:
        raise ValueError("Invalid clarification answer")
    envelope = AnswerEnvelope.model_validate(request.forwarded_props)
    thread_id, run_id, question_id = (
        UUID(request.thread_id),
        UUID(request.run_id),
        UUID(resume.interrupt_id),
    )
    return AnswerTurn(
        thread_id,
        run_id,
        AnswerInput(
            envelope.task_id,
            question_id,
            envelope.waiting_version,
            envelope.conditions_revision,
            envelope.key,
            answer,
            thread_id,
            run_id,
        ),
    )
