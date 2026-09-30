from uuid import UUID

import pytest

from whisky.modules.discovery.conditions import CatalogReference
from whisky.modules.discovery.proposal import (
    PreferenceProposal,
    PreferenceSuggestion,
    ReviewedFlavorMapping,
)


def mapping():
    return ReviewedFlavorMapping(
        feature_key="fruit",
        reference=CatalogReference(release_id=UUID(int=1), item_id=UUID(int=2)),
        evidence_ids=(UUID(int=3),),
    )


def proposal(mapped):
    return PreferenceProposal(
        summary="飲食線索仍待確認",
        preferences=(
            PreferenceSuggestion(
                description="可能喜歡果香",
                intent="prefer",
                source_quote="喜歡水果甜點",
                source_kind="food_clue",
                mapping=mapped,
            ),
        ),
    )


def test_confirmation_uses_the_reviewed_feature_key_without_promoting_the_clue():
    draft = proposal(mapping())
    draft.validate_source("我喜歡水果甜點")
    draft.validate_mappings((mapping(),), require_mapping=True)
    patch = draft.selected_patch((0,))
    assert patch.upsert_preferences[0].description == "fruit"
    assert patch.upsert_preferences[0].certainty == "user_stated"
    assert patch.upsert_preferences[0].strength == "soft"
    assert draft.preferences[0].description == "可能喜歡果香"
    assert draft.preferences[0].certainty == "inferred"


@pytest.mark.parametrize(
    "changes",
    [
        {"feature_key": "smoke"},
        {"reference": CatalogReference(release_id=UUID(int=9), item_id=UUID(int=2))},
        {"reference": CatalogReference(release_id=UUID(int=1), item_id=UUID(int=9))},
        {"evidence_ids": (UUID(int=9),)},
        {"evidence_ids": (UUID(int=3), UUID(int=3))},
    ],
)
def test_a_declared_mapping_must_match_real_reviewed_tag_provenance(changes):
    draft = proposal(mapping().model_copy(update=changes))
    with pytest.raises(ValueError, match="REVIEWED_MAPPING_NOT_FOUND"):
        draft.validate_mappings((mapping(),))


def test_automatic_proposals_require_a_mapping_or_no_claimed_preference():
    with pytest.raises(ValueError, match="REVIEWED_MAPPING_REQUIRED"):
        proposal(None).validate_mappings((mapping(),), require_mapping=True)
    proposal(None).validate_mappings((mapping(),))
    PreferenceProposal(summary="還不知道適合的風味").validate_mappings(
        (), require_mapping=True
    )
