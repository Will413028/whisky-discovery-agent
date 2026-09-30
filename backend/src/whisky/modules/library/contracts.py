"""Versioned library commands and private views."""

from datetime import date
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from whisky.modules.discovery.public import ResearchConditionsV1
from whisky.modules.library.domain import exploration_choice


def conclusion_schema(schema: dict[str, Any]) -> None:
    schema["allOf"] = [
        {
            "if": {"properties": {"outcome": {"const": "selected"}}},
            "then": {
                "properties": {
                    "selectedVersionId": {"not": {"type": "null"}},
                    "selectedBottleName": {"not": {"type": "null"}},
                    "alternativeVersionIds": {"maxItems": 2},
                }
            },
            "else": {
                "properties": {
                    "selectedVersionId": {"type": "null"},
                    "selectedBottleName": {"type": "null"},
                    "alternativeVersionIds": {"maxItems": 3},
                }
            },
        }
    ]


class LibraryModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class SaveConclusionV1(LibraryModel):
    schema_version: Literal[1] = 1
    key: str = Field(min_length=1, max_length=128)
    plan_id: UUID
    report_id: UUID
    expected_conditions_revision: int = Field(ge=1)
    selected_version_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=2000)
    tradeoff: str = Field(default="", max_length=2000)


class ConclusionContextViewV1(LibraryModel):
    schema_version: Literal[1] = 1
    plan_id: UUID
    task_id: UUID
    report_id: UUID
    conditions_revision: int = Field(ge=1)
    current_conditions_revision: int = Field(ge=1)


class ConclusionViewV1(LibraryModel):
    model_config = ConfigDict(json_schema_extra=conclusion_schema)
    schema_version: Literal[1] = 1
    id: UUID
    plan_id: UUID
    task_id: UUID
    report_id: UUID
    conditions_revision: int = Field(ge=1)
    conditions: ResearchConditionsV1
    catalog_release_id: UUID | None
    evaluated_on: date
    revision: int = Field(ge=1)
    outcome: Literal["selected", "no_suitable"]
    selected_version_id: UUID | None
    selected_bottle_name: str | None = Field(min_length=1)
    alternative_version_ids: tuple[UUID, ...] = Field(
        json_schema_extra={"uniqueItems": True}
    )
    reason: str
    tradeoff: str
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def consistent_choice(self) -> Self:
        versions = (
            *self.alternative_version_ids,
            *(
                (self.selected_version_id,)
                if self.selected_version_id is not None
                else ()
            ),
        )
        choice = exploration_choice(
            versions, self.selected_version_id, self.reason, self.tradeoff
        )
        if self.outcome != choice.outcome:
            raise ValueError("INVALID_CONCLUSION_OUTCOME")
        if (self.selected_version_id is None) != (self.selected_bottle_name is None):
            raise ValueError("INVALID_CONCLUSION_SELECTION_NAME")
        return self


class ConclusionListViewV1(LibraryModel):
    schema_version: Literal[1] = 1
    plan_id: UUID
    items: tuple[ConclusionViewV1, ...]
    next_cursor: str | None
