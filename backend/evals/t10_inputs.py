"""Typed fixture controls for the frozen T10 corpus, independent of model outputs."""

from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict

from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.research.inputs_v4 import ResearchInputV4
from whisky.modules.research.views import QuestionView


class CaseControls(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conditions: ResearchConditions
    input: ResearchInputV4
    version_choice: UUID | None = None
    proposal_action: Literal["capture_then_use_intent"] | None = None
    stop_at: Literal["proposal_question"] | None = None


def validated_cases(
    corpus: dict[str, Any], controls: dict[str, Any]
) -> dict[str, tuple[ResearchConditions, ResearchInputV4]]:
    cases = corpus["cases"]
    identifiers = [case["id"] for case in cases]
    if (
        controls.get("version") != 1
        or controls.get("corpus_version") != corpus["version"]
        or controls.get("frozen_before_model_run") is not True
        or len(identifiers) != len(set(identifiers))
        or set(controls.get("cases", {})) != set(identifiers)
    ):
        raise ValueError("EVAL_INPUT_CORPUS_MISMATCH")
    result = {}
    for case in cases:
        try:
            value = CaseControls.model_validate(controls["cases"][case["id"]])
        except ValueError as error:
            raise ValueError("EVAL_INPUT_INVALID_CONTROLS") from error
        if value.conditions.goal != case["input"] or (
            value.input.phase == "proposal" and value.input.source_text != case["input"]
        ):
            raise ValueError("EVAL_INPUT_REWRITTEN_SOURCE")
        if (value.input.phase == "proposal") != (value.proposal_action is not None):
            raise ValueError("EVAL_INPUT_PROPOSAL_ACTION_MISMATCH")
        result[case["id"]] = (value.conditions, value.input)
    return result


def select_answer(
    task_id: UUID, question: QuestionView, is_proposal: bool, controls: CaseControls
) -> UUID | None:
    if is_proposal:
        if controls.stop_at == "proposal_question":
            return None
        expected = uuid5(task_id, "proposal:use-intent")
        if controls.proposal_action == "capture_then_use_intent" and any(
            choice.id == expected for choice in question.choices
        ):
            return expected
    elif controls.version_choice is not None:
        choices = [
            choice.id
            for choice in question.choices
            if choice.id == controls.version_choice
        ]
        if len(choices) == 1:
            return choices[0]
    raise ValueError("EVAL_ANSWER_NOT_FOUND")
