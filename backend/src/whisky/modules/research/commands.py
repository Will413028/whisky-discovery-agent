"""Allowlisted application commands extracted from untrusted AG-UI input."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from ag_ui.core import RunAgentInput
from pydantic import Field, field_validator

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
