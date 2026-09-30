"""User choices are separate from reviewed facts and tasting preferences."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class ExplorationChoice:
    outcome: Literal["selected", "no_suitable"]
    selected_version_id: UUID | None
    alternative_version_ids: tuple[UUID, ...]
    reason: str
    tradeoff: str


def exploration_choice(
    candidate_versions: tuple[UUID, ...],
    selected_version_id: UUID | None,
    reason: str,
    tradeoff: str = "",
) -> ExplorationChoice:
    if len(candidate_versions) > 3 or len(set(candidate_versions)) != len(
        candidate_versions
    ):
        raise ValueError("INVALID_REPORT_CANDIDATES")
    if (
        selected_version_id is not None
        and selected_version_id not in candidate_versions
    ):
        raise ValueError("NOT_A_REPORT_CANDIDATE")
    reason = reason.strip()
    if not 1 <= len(reason) <= 2000:
        raise ValueError("INVALID_REASON")
    if len(tradeoff) > 2000:
        raise ValueError("INVALID_TRADEOFF")
    return ExplorationChoice(
        "selected" if selected_version_id is not None else "no_suitable",
        selected_version_id,
        tuple(
            version for version in candidate_versions if version != selected_version_id
        ),
        reason,
        tradeoff,
    )
