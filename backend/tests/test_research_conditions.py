import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from whisky.modules.discovery.conditions import ResearchConditions


def conditions(**changes):
    return ResearchConditions.model_validate(
        {"entry": "beginner", "goal": "探索果香", **changes}
    )


@pytest.mark.parametrize("certainty", ["inferred", "unknown"])
def test_unconfirmed_preferences_cannot_become_hard_constraints(certainty):
    with pytest.raises(ValidationError):
        conditions(
            preferences=[
                dict(
                    description="不要煙燻",
                    intent="avoid",
                    certainty=certainty,
                    strength="hard",
                )
            ]
        )


@pytest.mark.parametrize(
    "amount", ["0", "-1", "NaN", "Infinity", "-Infinity", "1e100000", "0.001"]
)
def test_budget_must_be_positive_finite_decimal(amount):
    with pytest.raises(ValidationError):
        conditions(budget_twd=amount)


def test_existing_bottle_entry_requires_versioned_catalog_reference():
    with pytest.raises(ValidationError):
        conditions(entry="existing_bottle")


@pytest.mark.parametrize(
    "changes",
    [
        {"goal": "   "},
        {"owner_id": str(uuid4())},
        {"schema_version": 2},
        {
            "preferences": [
                dict(
                    description=" ",
                    intent="prefer",
                    certainty="user_stated",
                    strength="soft",
                )
            ]
        },
    ],
)
def test_invalid_or_unrecognized_condition_fields_are_rejected(changes):
    with pytest.raises(ValidationError):
        conditions(**changes)


def test_equivalent_money_and_whitespace_have_one_canonical_payload():
    left = conditions(goal="  探索果香  ", budget_twd="1000.00")
    right = conditions(budget_twd="1E3")
    assert left.canonical_json() == right.canonical_json()


def test_snapshot_preserves_confirmed_and_inferred_preferences_separately():
    reference = {"release_id": str(uuid4()), "item_id": str(uuid4())}
    preferences = [
        dict(
            description="保留果香",
            intent="keep",
            certainty="user_stated",
            strength="soft",
        ),
        dict(
            description="可能喜歡香草",
            intent="prefer",
            certainty="inferred",
            strength="soft",
        ),
        dict(
            description="不要煙燻",
            intent="avoid",
            certainty="user_stated",
            strength="hard",
        ),
    ]
    original = conditions(
        entry="existing_bottle", starting_bottle=reference, preferences=preferences
    )
    snapshot = json.loads(original.canonical_json())
    assert snapshot["preferences"] == preferences
    assert snapshot["starting_bottle"] == reference
    assert snapshot["budget_twd"] is None
    assert ResearchConditions.model_validate(snapshot) == original


def test_conditions_cannot_be_mutated_after_validation():
    value = conditions()
    with pytest.raises(ValidationError):
        value.goal = "changed outside a revision command"
