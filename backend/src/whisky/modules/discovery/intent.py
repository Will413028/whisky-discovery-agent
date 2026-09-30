"""Structured exploration direction, separate from frozen V1 conditions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ExplorationMode = Literal["style_options", "similar", "small_step", "contrast"]


class FlavorContrast(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    axis: Literal["flavor_description"] = "flavor_description"
    origin_feature: str = Field(min_length=1, max_length=1000)
    candidate_feature: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def different_features(self) -> "FlavorContrast":
        if self.origin_feature == self.candidate_feature:
            raise ValueError("Contrast requires two different sourced descriptors")
        return self


class ExplorationIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    origin_query: str | None = Field(default=None, min_length=1, max_length=1000)
    mode: ExplorationMode = "style_options"
    explore_feature: str | None = Field(default=None, min_length=1, max_length=1000)
    smoke_comparison: bool = False
    contrast: FlavorContrast | None = None
