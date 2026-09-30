"""Frozen version 1 research conditions for persisted plans and control records.

Retain this codec when later conditions versions are introduced so old external
commands and Temporal payloads remain recoverable.
"""

import json
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


class ConditionsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CatalogReference(ConditionsModel):
    release_id: UUID
    item_id: UUID


class Preference(ConditionsModel):
    description: str = Field(min_length=1, max_length=1000)
    intent: Literal["prefer", "keep", "change", "avoid"]
    certainty: Literal["user_stated", "inferred", "unknown"]
    strength: Literal["soft", "hard"]

    @model_validator(mode="after")
    def confirmed_hard_constraint(self) -> Self:
        if self.strength == "hard" and self.certainty != "user_stated":
            raise ValueError("Hard constraints require an explicit user statement")
        return self


class ResearchConditions(ConditionsModel):
    schema_version: Literal[1] = 1
    entry: Literal["beginner", "existing_bottle"]
    goal: str = Field(min_length=1, max_length=2000)
    starting_bottle: CatalogReference | None = None
    preferences: tuple[Preference, ...] = Field(default=(), max_length=64)
    budget_twd: Decimal | None = Field(
        default=None, gt=0, allow_inf_nan=False, max_digits=18, decimal_places=2
    )

    @model_validator(mode="after")
    def versioned_start(self) -> Self:
        if self.entry == "existing_bottle" and self.starting_bottle is None:
            raise ValueError("An existing bottle entry requires a catalog reference")
        return self

    @field_serializer("budget_twd")
    def serialize_budget(self, value: Decimal | None) -> str | None:
        if value is None:
            return None
        whole, dot, fraction = format(value, "f").partition(".")
        fraction = fraction.rstrip("0")
        return whole + dot + fraction if fraction else whole

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )


ResearchConditionsV1 = ResearchConditions
