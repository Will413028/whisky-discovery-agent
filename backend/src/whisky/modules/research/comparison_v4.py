"""V4 comparison artifacts retain both sides of reviewed evidence."""

from dataclasses import dataclass
from typing import Literal

from whisky.modules.discovery.public import (
    CatalogReference,
    ExplorationIntent,
    ExplorationMode,
    ResearchConditions,
)
from whisky.modules.research.contracts import (
    ResearchCatalogItem,
    ResearchCatalogSnapshot,
)
from whisky.modules.research.report import ReportClaim
from whisky.modules.research.selection_v4 import ExplorationSelection, select_research


@dataclass(frozen=True)
class DescriptorDifferenceV4:
    axis: Literal["flavor_description"]
    origin_feature: str
    candidate_feature: str
    origin_claims: tuple[ReportClaim, ...]
    candidate_claims: tuple[ReportClaim, ...]


@dataclass(frozen=True)
class CandidateComparisonV4:
    candidate: CatalogReference
    mode: ExplorationMode
    origin: CatalogReference | None
    common_tags: tuple[str, ...]
    origin_claims: tuple[ReportClaim, ...]
    candidate_claims: tuple[ReportClaim, ...]
    origin_description: ReportClaim | None
    candidate_description: ReportClaim | None
    difference: DescriptorDifferenceV4 | None
    explore_claims: tuple[ReportClaim, ...]


@dataclass(frozen=True)
class ComparisonArtifactV4:
    intent: ExplorationIntent
    candidates: tuple[CandidateComparisonV4, ...]
    unresolved: tuple[str, ...]
    unlisted_name: str | None
    schema_version: Literal[4] = 4


def _description(item: ResearchCatalogItem | None) -> ReportClaim | None:
    if item is None:
        return None
    return next(
        (
            claim
            for claim in item.claims
            if claim.kind == "fact"
            and claim.key == "producer_tasting_notes"
            and claim.evidence_ids
        ),
        None,
    )


def comparison_artifact_v4(
    conditions: ResearchConditions,
    snapshot: ResearchCatalogSnapshot,
    selected_version_id: str | None,
    intent: ExplorationIntent,
    selection: ExplorationSelection,
) -> ComparisonArtifactV4:
    """Reject substituted evidence and keep distinct origin/candidate citations."""
    expected = select_research(conditions, snapshot, selected_version_id, intent=intent)
    if selection != expected or selection.version_indices:
        raise ValueError("COMPARISON_MISMATCH")
    items = {item.index: item for item in snapshot.items}
    references = {(item.release_id, item.item_id): item for item in snapshot.items}
    comparisons = []
    for evidence in selection.comparisons:
        candidate = items[evidence.item_index]
        origin = (
            references[
                (
                    evidence.origin_reference.release_id,
                    evidence.origin_reference.item_id,
                )
            ]
            if evidence.origin_reference is not None
            else None
        )
        difference = evidence.difference
        comparisons.append(
            CandidateComparisonV4(
                candidate=CatalogReference(
                    release_id=candidate.release_id, item_id=candidate.item_id
                ),
                mode=evidence.mode,
                origin=evidence.origin_reference,
                common_tags=evidence.common_tags,
                origin_claims=evidence.origin_claims,
                candidate_claims=evidence.candidate_claims,
                origin_description=_description(origin),
                candidate_description=_description(candidate),
                difference=(
                    DescriptorDifferenceV4(
                        difference.axis,
                        difference.origin_feature,
                        difference.candidate_feature,
                        difference.origin_claims,
                        difference.candidate_claims,
                    )
                    if difference is not None
                    else None
                ),
                explore_claims=evidence.explore_claims,
            )
        )
    return ComparisonArtifactV4(
        intent, tuple(comparisons), selection.unresolved, selection.unlisted_name
    )
