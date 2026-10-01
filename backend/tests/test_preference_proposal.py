import pytest
from pydantic import ValidationError

from whisky.modules.discovery.condition_patch import apply_condition_patch
from whisky.modules.discovery.conditions import Preference, ResearchConditions
from whisky.modules.discovery.proposal import (
    BudgetSuggestion,
    PreferenceProposal,
    PreferenceSuggestion,
)


def hint():
    return PreferenceSuggestion(
        description="甜香",
        intent="prefer",
        source_quote="喜歡甜點",
        source_kind="food_clue",
    )


def test_food_clues_remain_unconfirmed_soft_and_require_real_source_quotes():
    proposal = PreferenceProposal(summary="待確認甜香線索", preferences=(hint(),))
    proposal.validate_source("我喜歡甜點，還不知道適合什麼威士忌")
    assert proposal.preferences[0].certainty == "inferred"
    assert proposal.preferences[0].strength == "soft"
    with pytest.raises(ValueError, match="SOURCE_QUOTE_NOT_FOUND"):
        proposal.validate_source("我不知道喜歡什麼")


def test_only_selected_hints_are_confirmed_and_hard_requires_explicit_choice():
    proposal = PreferenceProposal(
        summary="待確認",
        preferences=(
            hint(),
            PreferenceSuggestion(
                description="果香",
                intent="keep",
                source_quote="保留果香",
                source_kind="direct_description",
            ),
        ),
    )
    patch = proposal.selected_patch((0,))
    assert len(patch.upsert_preferences) == 1
    assert patch.upsert_preferences[0].description == "甜香"
    assert patch.upsert_preferences[0].certainty == "user_stated"
    assert patch.upsert_preferences[0].strength == "soft"
    assert (
        proposal.selected_patch((0,), hard=(0,)).upsert_preferences[0].strength
        == "hard"
    )
    with pytest.raises(ValueError, match="INVALID_SELECTION"):
        proposal.selected_patch((0,), hard=(1,))


def test_selected_budget_change_uses_same_patch_and_preserves_unmentioned_preferences():
    old = ResearchConditions(
        entry="beginner",
        goal="保留果香",
        budget_twd="1000",
        preferences=(
            Preference(
                description="果香",
                intent="keep",
                certainty="user_stated",
                strength="soft",
            ),
        ),
    )
    proposal = PreferenceProposal(
        summary="只改本次預算",
        budget=BudgetSuggestion(action="set", amount_twd="900", source_quote="改成900"),
    )
    proposal.validate_source("預算改成900，其他一樣")
    patch = proposal.selected_patch((), include_budget=True)
    assert "goal" not in patch.model_fields_set
    result = apply_condition_patch(old, patch.model_dump(exclude_unset=True))
    assert (
        result.budget_twd == 900
        and result.preferences == old.preferences
        and result.goal == old.goal
    )
    assert "budget_twd" not in proposal.selected_patch(()).model_fields_set


@pytest.mark.parametrize("selected", [(2,), (0, 0), (-1,)])
def test_invalid_selection_is_rejected(selected):
    with pytest.raises(ValueError, match="INVALID_SELECTION"):
        PreferenceProposal(summary="待確認", preferences=(hint(),)).selected_patch(
            selected
        )


def test_model_cannot_declare_a_hard_or_user_stated_preference():
    for forged in ({"certainty": "user_stated"}, {"strength": "hard"}):
        with pytest.raises(ValidationError):
            PreferenceSuggestion.model_validate({**hint().model_dump(), **forged})


def test_summary_reserves_question_space_for_the_confirmation_instructions():
    assert PreferenceProposal(summary="甲" * 1600).summary == "甲" * 1600
    with pytest.raises(ValidationError):
        PreferenceProposal(summary="甲" * 1601)
