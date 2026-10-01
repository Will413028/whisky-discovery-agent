"""Explicit bottle feedback does not infer preferences from catalog tags."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class BottleFeedback:
    want_to_explore: bool
    tasting: Literal["not_tasted", "liked", "disliked"]
    tasting_reason: str


def bottle_feedback(
    want_to_explore: bool,
    tasting: Literal["not_tasted", "liked", "disliked"],
    tasting_reason: str = "",
) -> BottleFeedback:
    reason = tasting_reason.strip()
    if len(reason) > 2000 or (tasting == "not_tasted" and reason):
        raise ValueError("INVALID_TASTING_REASON")
    return BottleFeedback(want_to_explore, tasting, reason)
