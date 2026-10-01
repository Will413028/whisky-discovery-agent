from uuid import UUID

import pytest
from pydantic import ValidationError

from whisky.modules.library.contracts import ConclusionViewV1

FIRST = UUID("00000000-0000-4000-8000-000000000001")
SECOND = UUID("00000000-0000-4000-8000-000000000002")
THIRD = UUID("00000000-0000-4000-8000-000000000003")
FOURTH = UUID("00000000-0000-4000-8000-000000000004")
BASE = dict(
    id=FIRST,
    plan_id=FIRST,
    task_id=FIRST,
    report_id=FIRST,
    conditions_revision=1,
    conditions=dict(
        schema_version=1,
        entry="beginner",
        goal="合成條件",
        budget_twd=None,
        starting_bottle=None,
        preferences=[],
    ),
    catalog_release_id=None,
    evaluated_on="2026-09-30",
    revision=1,
    outcome="selected",
    selected_version_id=FIRST,
    selected_bottle_name="合成候選十二年",
    alternative_version_ids=(SECOND,),
    reason="合成的明確選擇",
    tradeoff="",
    created_at="2026-09-30T00:00:00Z",
    updated_at="2026-09-30T00:00:00Z",
)


@pytest.mark.parametrize(
    "change",
    [
        {"selected_version_id": None},
        {"outcome": "no_suitable"},
        {"alternative_version_ids": (FIRST, SECOND)},
        {"alternative_version_ids": (SECOND, THIRD, FOURTH)},
        {"alternative_version_ids": (SECOND, SECOND)},
    ],
)
def test_a_private_conclusion_view_cannot_claim_an_inconsistent_choice(change):
    with pytest.raises(ValidationError):
        ConclusionViewV1.model_validate({**BASE, **change})


def test_selected_and_no_suitable_views_preserve_explicit_unknown_selection():
    selected = ConclusionViewV1.model_validate(BASE)
    rejected = ConclusionViewV1.model_validate(
        {
            **BASE,
            "outcome": "no_suitable",
            "selected_version_id": None,
            "selected_bottle_name": None,
        }
    )
    assert selected.selected_version_id == FIRST
    assert rejected.selected_version_id is None
