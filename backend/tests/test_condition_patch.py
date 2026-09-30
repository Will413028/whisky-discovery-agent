from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from whisky.modules.discovery.condition_patch import apply_condition_patch
from whisky.modules.discovery.conditions import (
    CatalogReference,
    Preference,
    ResearchConditions,
)


def original():
    return ResearchConditions(
        entry="existing_bottle",
        goal="保留果香，想找下一款",
        starting_bottle=CatalogReference(release_id=uuid4(), item_id=uuid4()),
        budget_twd=Decimal("1000"),
        preferences=(
            Preference(
                description="果香",
                intent="keep",
                certainty="user_stated",
                strength="soft",
            ),
            Preference(
                description="香草甜香",
                intent="change",
                certainty="user_stated",
                strength="soft",
            ),
        ),
    )


def test_budget_patch_preserves_every_unmentioned_condition_and_original():
    before = original()
    after = apply_condition_patch(before, {"budget_twd": "900"})
    assert after.budget_twd == Decimal("900")
    assert after.model_dump(exclude={"budget_twd"}) == before.model_dump(
        exclude={"budget_twd"}
    )
    assert before.budget_twd == Decimal("1000")


def test_explicit_null_removes_budget_while_omission_keeps_it():
    before = original()
    assert apply_condition_patch(before, {"budget_twd": None}).budget_twd is None
    assert (
        apply_condition_patch(before, {"goal": "新的探索目標"}).budget_twd
        == before.budget_twd
    )


def test_upsert_and_explicit_remove_affect_only_named_preferences():
    before = original()
    after = apply_condition_patch(
        before,
        {
            "remove_preferences": ["香草甜香"],
            "upsert_preferences": [
                {
                    "description": "太妃糖",
                    "intent": "change",
                    "certainty": "user_stated",
                    "strength": "soft",
                }
            ],
        },
    )
    assert after.preferences[0] == before.preferences[0]
    assert [preference.description for preference in after.preferences] == [
        "果香",
        "太妃糖",
    ]
    assert after.budget_twd == before.budget_twd
    assert after.starting_bottle == before.starting_bottle


@pytest.mark.parametrize(
    "raw",
    [
        {"owner_id": str(uuid4())},
        {"schema_version": 2},
        {"budget_twd": "NaN"},
        {"goal": None},
        {"starting_bottle": None},
        {
            "upsert_preferences": [
                {
                    "description": "果香",
                    "intent": "keep",
                    "certainty": "inferred",
                    "strength": "hard",
                }
            ]
        },
    ],
)
def test_patch_cannot_bypass_conditions_identity_or_confirmed_hard_rules(raw):
    with pytest.raises(ValidationError):
        apply_condition_patch(original(), raw)


def test_empty_or_no_effect_patch_does_not_create_revision_churn():
    before = original()
    for raw in ({}, {"goal": before.goal}, {"remove_preferences": ["不在偏好中"]}):
        with pytest.raises(ValueError, match="NO_CONDITION_CHANGE"):
            apply_condition_patch(before, raw)


def test_duplicate_edits_do_not_silently_choose_the_last_intent():
    before = original()
    first = before.preferences[0].model_dump()
    second = {**first, "intent": "avoid"}
    with pytest.raises(ValueError, match="DUPLICATE_PREFERENCE_EDIT"):
        apply_condition_patch(before, {"upsert_preferences": [first, second]})


def test_ambiguous_legacy_preference_requires_explicit_removal_before_replacement():
    before = original()
    before = before.model_copy(
        update={
            "preferences": (
                *before.preferences,
                before.preferences[0].model_copy(update={"intent": "avoid"}),
            )
        }
    )
    replacement = before.preferences[0].model_copy(update={"strength": "hard"})
    with pytest.raises(ValueError, match="AMBIGUOUS_PREFERENCE"):
        apply_condition_patch(
            before, {"upsert_preferences": [replacement.model_dump()]}
        )
    after = apply_condition_patch(
        before,
        {
            "remove_preferences": ["果香"],
            "upsert_preferences": [replacement.model_dump()],
        },
    )
    assert [p for p in after.preferences if p.description == "果香"] == [replacement]
    assert before.preferences[1] in after.preferences
