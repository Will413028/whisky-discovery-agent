"""Explicit long-term preferences, independent of one exploration's budget."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class StatedPreference:
    description: str
    intent: Literal["prefer", "avoid"]
    strength: Literal["soft", "hard"]
    statement: str


def stated_preferences(
    values: tuple[StatedPreference, ...],
) -> tuple[StatedPreference, ...]:
    if len(values) > 64:
        raise ValueError("TOO_MANY_PREFERENCES")
    normalized = []
    for value in values:
        description = value.description.strip()
        statement = value.statement.strip()
        if (
            not description
            or len(description) > 1000
            or not statement
            or len(statement) > 2000
        ):
            raise ValueError("INVALID_PREFERENCE_STATEMENT")
        if value.intent not in {"prefer", "avoid"} or value.strength not in {
            "soft",
            "hard",
        }:
            raise ValueError("INVALID_LONG_TERM_PREFERENCE")
        normalized.append(
            StatedPreference(description, value.intent, value.strength, statement)
        )
    if len({value.description for value in normalized}) != len(normalized):
        raise ValueError("DUPLICATE_PREFERENCE")
    return tuple(normalized)
