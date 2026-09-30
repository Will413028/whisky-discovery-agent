"""Only reviewed tag claims may anchor an unconfirmed taste mapping."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from whisky.modules.discovery.public import CatalogReference, ReviewedFlavorMapping

if TYPE_CHECKING:
    from whisky.modules.catalog.public import ReviewedFlavorReference


@dataclass(frozen=True)
class ProposalContextV4:
    source_text: str
    mappings: tuple[ReviewedFlavorMapping, ...]


def proposal_context_v4(
    source_text: str, references: tuple["ReviewedFlavorReference", ...]
) -> ProposalContextV4:
    mappings: dict[str, ReviewedFlavorMapping] = {}
    for reference in references:
        if reference.evidence_ids and reference.label not in mappings:
            mappings[reference.label] = ReviewedFlavorMapping(
                feature_key=reference.label,
                reference=CatalogReference(
                    release_id=reference.release_id, item_id=reference.item_id
                ),
                evidence_ids=reference.evidence_ids,
            )
    return ProposalContextV4(
        source_text, tuple(mappings[key] for key in sorted(mappings))
    )
