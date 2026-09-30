"""Immutable V4 input; legacy start payloads retain their original digest."""

from dataclasses import dataclass
from typing import Literal, Self
from uuid import UUID

from ag_ui.core import RunAgentInput
from pydantic import Field, model_validator

from whisky.modules.discovery.public import ExplorationIntent
from whisky.modules.research.views import ViewModel


class ResearchInputV4(ViewModel):
    schema_version: Literal[4] = 4
    phase: Literal["proposal", "research"] = "research"
    source_text: str | None = Field(default=None, min_length=1, max_length=2000)
    intent: ExplorationIntent = Field(default_factory=ExplorationIntent)

    @model_validator(mode="after")
    def proposal_source(self) -> Self:
        if self.phase == "proposal" and (
            self.source_text is None or not self.source_text.strip()
        ):
            raise ValueError("A proposal requires its original description")
        if self.phase == "research" and self.source_text is not None:
            raise ValueError("Confirmed research must not reinterpret raw descriptions")
        return self


class StartCommandV4(ViewModel):
    type: Literal["start_v4"]
    key: str = Field(min_length=1, max_length=128)
    plan_id: UUID
    conditions_revision: int = Field(ge=1)
    input: ResearchInputV4
    source_task_id: UUID | None = None

    @model_validator(mode="after")
    def nonblank_key(self) -> Self:
        if not self.key.strip():
            raise ValueError("Command key must not be blank")
        return self


@dataclass(frozen=True)
class StartTurnV4:
    thread_id: UUID
    run_id: UUID
    command: StartCommandV4


def parse_start_v4(request: RunAgentInput) -> StartTurnV4:
    if request.resume or request.parent_run_id is not None:
        raise ValueError("Start cannot carry resume or parent-run semantics")
    return StartTurnV4(
        UUID(request.thread_id),
        UUID(request.run_id),
        StartCommandV4.model_validate(request.forwarded_props),
    )
