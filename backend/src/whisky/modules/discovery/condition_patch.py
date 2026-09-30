"""Partial edits to one exploration, independent of command transport."""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from whisky.modules.discovery.conditions import (
    CatalogReference,
    Preference,
    ResearchConditions,
)


class ConditionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    goal: str | None = None
    budget_twd: Decimal | None = None
    entry: Literal["beginner", "existing_bottle"] | None = None
    starting_bottle: CatalogReference | None = None
    upsert_preferences: tuple[Preference, ...] = Field(default=(), max_length=64)
    remove_preferences: tuple[str, ...] = Field(default=(), max_length=64)


def apply_condition_patch(
    conditions: ResearchConditions, raw: dict[str, Any]
) -> ResearchConditions:
    patch = ConditionPatch.model_validate(raw)
    descriptions = [preference.description for preference in patch.upsert_preferences]
    if len(set(descriptions)) != len(descriptions):
        raise ValueError("DUPLICATE_PREFERENCE_EDIT")
    values = conditions.model_dump()
    for field in ("goal", "budget_twd", "entry", "starting_bottle"):
        if field in patch.model_fields_set:
            values[field] = getattr(patch, field)
    preferences = [
        preference
        for preference in conditions.preferences
        if preference.description not in patch.remove_preferences
    ]
    for proposed in patch.upsert_preferences:
        matches = [
            index
            for index, existing in enumerate(preferences)
            if existing.description == proposed.description
        ]
        if len(matches) > 1:
            raise ValueError("AMBIGUOUS_PREFERENCE")
        if matches:
            preferences[matches[0]] = proposed
        else:
            preferences.append(proposed)
    values["preferences"] = preferences
    result = ResearchConditions.model_validate(values)
    if result == conditions:
        raise ValueError("NO_CONDITION_CHANGE")
    return result
