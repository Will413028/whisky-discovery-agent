"""Reviewed evidence policy over confirmed, structured exploration inputs."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from whisky.modules.discovery.public import CatalogReference, ResearchConditions
from whisky.modules.research.contracts import (
    ResearchCatalogItem,
    ResearchCatalogSnapshot,
)
from whisky.modules.research.report import ReportClaim

SELECTION_POLICY_VERSION = "catalog-selection-v4-1"
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


@dataclass(frozen=True)
class ContrastEvidence:
    axis: Literal["flavor_description"]
    origin_feature: str
    candidate_feature: str
    origin_claims: tuple[ReportClaim, ...]
    candidate_claims: tuple[ReportClaim, ...]


@dataclass(frozen=True)
class ComparisonEvidence:
    item_index: int
    mode: ExplorationMode
    common_tags: tuple[str, ...]
    origin_reference: CatalogReference | None
    origin_claims: tuple[ReportClaim, ...]
    candidate_claims: tuple[ReportClaim, ...]
    difference: ContrastEvidence | None = None
    explore_claims: tuple[ReportClaim, ...] = ()


@dataclass(frozen=True)
class ExplorationSelection:
    version_indices: tuple[int, ...]
    candidate_indices: tuple[int, ...]
    unlisted_name: str | None = None
    unresolved: tuple[str, ...] = ()
    comparisons: tuple[ComparisonEvidence, ...] = ()


def _tag_claims(item: ResearchCatalogItem) -> tuple[ReportClaim, ...]:
    return tuple(
        claim for claim in item.claims if claim.kind == "tag" and claim.evidence_ids
    )


def _notes(item: ResearchCatalogItem) -> tuple[ReportClaim, ...]:
    return tuple(
        claim
        for claim in item.claims
        if claim.kind == "fact"
        and claim.key == "producer_tasting_notes"
        and claim.evidence_ids
    )


def select_research(
    conditions: ResearchConditions,
    snapshot: ResearchCatalogSnapshot,
    selected_version_id: str | None,
    *,
    intent: ExplorationIntent | None = None,
) -> ExplorationSelection:
    request = intent or ExplorationIntent()
    items = snapshot.items
    origin = None
    if conditions.starting_bottle is not None:
        reference = conditions.starting_bottle
        origin = next(
            (
                item
                for item in items
                if (item.release_id, item.item_id)
                == (reference.release_id, reference.item_id)
            ),
            None,
        )
        if origin is None:
            return ExplorationSelection(
                (), (), unresolved=("起點酒款已不在目前已覆核資料中，請重新確認版本。",)
            )
    if selected_version_id is not None:
        selected = next(
            (
                item
                for item in items
                if str(item.bottle_version_id) == selected_version_id
            ),
            None,
        )
        if selected is None or (origin is not None and selected != origin):
            return ExplorationSelection(
                (), (), unresolved=("所選版本無法對應本次已覆核起點，請重新確認。",)
            )
        origin = selected
    if origin is None and request.origin_query is not None:
        query = request.origin_query.casefold()
        exact = tuple(
            item.index
            for item in items
            if query in {item.name.casefold(), item.official_name.casefold()}
        )
        matching = exact or tuple(
            item.index
            for item in items
            if query in item.name.casefold() or query in item.official_name.casefold()
        )
        if matching:
            return ExplorationSelection(matching, ())
        return ExplorationSelection((), (), request.origin_query)

    eligible = [item for item in items if item.eligible and item != origin]
    unresolved = []
    tags = {
        item.index: {claim.key: claim for claim in _tag_claims(item)} for item in items
    }
    for preference in conditions.preferences:
        if preference.strength != "hard":
            continue
        label = preference.description
        if preference.intent in {"prefer", "keep"}:
            eligible = [item for item in eligible if label in tags[item.index]]
            if not eligible:
                unresolved.append(
                    f"已覆核資料無法證實硬偏好「{label}」符合要求，未列為候選。"
                )
        else:
            eligible = []
            unresolved.append(
                f"已覆核資料無法證實硬偏好「{label}」符合要求，未列為候選。"
            )
    if request.smoke_comparison:
        unresolved.append(
            "已覆核資料沒有一致的煙燻比較尺度，不能以缺少標籤推論更少煙燻；請確認其他可比較條件。"
        )

    confirmed = {
        preference.description
        for preference in conditions.preferences
        if preference.certainty == "user_stated"
        and preference.intent in {"prefer", "keep"}
    }
    retained = {
        preference.description
        for preference in conditions.preferences
        if preference.certainty == "user_stated" and preference.intent == "keep"
    }
    familiar = set(tags[origin.index]) if origin is not None else confirmed
    comparisons = []
    for item in eligible:
        item_tags = tags[item.index]
        common = tuple(sorted(familiar.intersection(item_tags)))
        origin_claims = (
            tuple(tags[origin.index][label] for label in common)
            if origin is not None
            else ()
        )
        candidate_claims = tuple(item_tags[label] for label in common)
        difference = None
        contrast = request.contrast
        if origin is not None and contrast is not None:
            left = tuple(
                claim
                for claim in (*_tag_claims(origin), *_notes(origin))
                if contrast.origin_feature in claim.value
            )
            right = tuple(
                claim
                for claim in (*_tag_claims(item), *_notes(item))
                if contrast.candidate_feature in claim.value
            )
            if left and right:
                difference = ContrastEvidence(
                    contrast.axis,
                    contrast.origin_feature,
                    contrast.candidate_feature,
                    left,
                    right,
                )
        explore = tuple(
            claim
            for claim in (*_tag_claims(item), *_notes(item))
            if request.explore_feature is not None
            and request.explore_feature in claim.value
        )
        if request.mode == "similar" and not common:
            continue
        if request.mode == "small_step" and (
            not retained
            or not retained.issubset(item_tags)
            or not explore
            or (origin is not None and not retained.issubset(tags[origin.index]))
        ):
            continue
        if request.mode == "contrast" and not difference:
            continue
        if request.mode == "style_options":
            candidate_claims = _tag_claims(item) or _notes(item)
            if not candidate_claims:
                continue
        comparisons.append(
            ComparisonEvidence(
                item.index,
                request.mode,
                common,
                CatalogReference(release_id=origin.release_id, item_id=origin.item_id)
                if origin is not None
                else None,
                origin_claims,
                candidate_claims,
                difference,
                explore,
            )
        )

    def score(comparison: ComparisonEvidence) -> tuple[int, int]:
        common_score = len(comparison.common_tags) if request.mode == "similar" else 0
        stated_score = sum(
            1 if preference.intent in {"prefer", "keep"} else -1
            for preference in conditions.preferences
            if preference.certainty == "user_stated"
            and preference.strength == "soft"
            and preference.intent in {"prefer", "keep", "avoid"}
            and preference.description in tags[comparison.item_index]
        )
        return common_score, stated_score

    ordered = sorted(comparisons, key=score, reverse=True)[:3]
    if not ordered and eligible and request.mode != "style_options":
        unresolved.append(
            "目前已覆核資料無法支持本次探索方向；未以其他候選補滿，請確認可比較條件。"
        )
    return ExplorationSelection(
        (),
        tuple(comparison.item_index for comparison in ordered),
        unresolved=tuple(unresolved),
        comparisons=tuple(ordered),
    )
