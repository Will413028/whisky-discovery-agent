"""Unconfirmed model suggestions; only explicit selections become a patch."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from whisky.modules.discovery.condition_patch import ConditionPatch
from whisky.modules.discovery.conditions import CatalogReference, Preference
from whisky.modules.discovery.intent import ExplorationIntent


class ProposalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ReviewedFlavorMapping(ProposalModel):
    feature_key: str = Field(min_length=1, max_length=1000)
    reference: CatalogReference
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)


class PreferenceSuggestion(ProposalModel):
    description: str = Field(min_length=1, max_length=1000)
    intent: Literal["prefer", "keep", "change", "avoid"]
    source_quote: str = Field(min_length=1, max_length=2000)
    source_kind: Literal["direct_description", "food_clue", "uncertain"]
    certainty: Literal["inferred"] = "inferred"
    strength: Literal["soft"] = "soft"
    mapping: ReviewedFlavorMapping | None = None


class BudgetSuggestion(ProposalModel):
    action: Literal["set", "clear"]
    amount_twd: Decimal | None = Field(
        default=None, gt=0, allow_inf_nan=False, max_digits=18, decimal_places=2
    )
    source_quote: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def amount_pair(self) -> "BudgetSuggestion":
        if (self.action == "set") != (self.amount_twd is not None):
            raise ValueError("A set budget requires an amount; clear has no amount")
        return self


class PreferenceProposal(ProposalModel):
    summary: str = Field(min_length=1, max_length=1600)
    intent: ExplorationIntent = Field(default_factory=ExplorationIntent)
    preferences: tuple[PreferenceSuggestion, ...] = Field(default=(), max_length=8)
    budget: BudgetSuggestion | None = None

    def validate_mappings(
        self,
        allowed: tuple[ReviewedFlavorMapping, ...],
        *,
        require_mapping: bool = False,
    ) -> None:
        for suggestion in self.preferences:
            mapping = suggestion.mapping
            if mapping is None:
                if require_mapping:
                    raise ValueError("REVIEWED_MAPPING_REQUIRED")
                continue
            if len(set(mapping.evidence_ids)) != len(mapping.evidence_ids) or not any(
                mapping.feature_key == candidate.feature_key
                and mapping.reference.release_id == candidate.reference.release_id
                and mapping.reference.item_id == candidate.reference.item_id
                and set(mapping.evidence_ids) == set(candidate.evidence_ids)
                for candidate in allowed
            ):
                raise ValueError("REVIEWED_MAPPING_NOT_FOUND")

    def validate_source(self, source_text: str) -> None:
        quotes = [value.source_quote for value in self.preferences]
        if self.budget is not None:
            quotes.append(self.budget.source_quote)
        if not source_text.strip() or any(quote not in source_text for quote in quotes):
            raise ValueError("SOURCE_QUOTE_NOT_FOUND")

    def selected_patch(
        self,
        selected: tuple[int, ...],
        hard: tuple[int, ...] = (),
        *,
        include_budget: bool = False,
    ) -> ConditionPatch:
        if (
            any(
                type(index) is not int or not 0 <= index < len(self.preferences)
                for index in (*selected, *hard)
            )
            or len(set(selected)) != len(selected)
            or len(set(hard)) != len(hard)
            or not set(hard).issubset(selected)
            or (include_budget and self.budget is None)
        ):
            raise ValueError("INVALID_SELECTION")
        preferences: list[Preference] = []
        for index in selected:
            suggestion = self.preferences[index]
            mapping = suggestion.mapping
            preferences.append(
                Preference(
                    description=mapping.feature_key
                    if mapping is not None
                    else suggestion.description,
                    intent=suggestion.intent,
                    certainty="user_stated",
                    strength="hard" if index in hard else "soft",
                )
            )
        if include_budget and self.budget is not None:
            return ConditionPatch(
                upsert_preferences=tuple(preferences), budget_twd=self.budget.amount_twd
            )
        return ConditionPatch(upsert_preferences=tuple(preferences))
