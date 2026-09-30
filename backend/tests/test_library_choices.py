from uuid import UUID

import pytest

from whisky.modules.library.domain import exploration_choice

FIRST = UUID("00000000-0000-4000-8000-000000000001")
SECOND = UUID("00000000-0000-4000-8000-000000000002")
THIRD = UUID("00000000-0000-4000-8000-000000000003")
FOREIGN = UUID("00000000-0000-4000-8000-000000000004")


def test_selection_keeps_the_exact_version_and_other_report_candidates():
    choice = exploration_choice(
        (FIRST, SECOND, THIRD), SECOND, " 保留果香 ", "價錢較高"
    )
    assert choice.outcome == "selected"
    assert choice.selected_version_id == SECOND
    assert choice.alternative_version_ids == (FIRST, THIRD)
    assert (choice.reason, choice.tradeoff) == ("保留果香", "價錢較高")


def test_no_suitable_preserves_the_rejected_alternatives_without_inventing_a_choice():
    choice = exploration_choice((FIRST,), None, "沒有符合想要的方向")
    assert choice.outcome == "no_suitable"
    assert choice.selected_version_id is None
    assert choice.alternative_version_ids == (FIRST,)


@pytest.mark.parametrize("reason", ["", " \n ", "x" * 2001])
def test_a_saved_choice_requires_a_bounded_explicit_reason(reason):
    with pytest.raises(ValueError, match="INVALID_REASON"):
        exploration_choice((FIRST,), FIRST, reason)


def test_a_version_outside_the_completed_report_cannot_be_selected():
    with pytest.raises(ValueError, match="NOT_A_REPORT_CANDIDATE"):
        exploration_choice((FIRST, SECOND), FOREIGN, "我選別的")


def test_no_result_can_still_save_an_explicit_no_suitable_conclusion():
    choice = exploration_choice((), None, "沒有符合硬限制的酒款")
    assert choice.outcome == "no_suitable" and choice.alternative_version_ids == ()


def test_tradeoffs_are_bounded_user_text_instead_of_unlimited_history():
    with pytest.raises(ValueError, match="INVALID_TRADEOFF"):
        exploration_choice((FIRST,), FIRST, "保留果香", "x" * 2001)


@pytest.mark.parametrize(
    "candidates", [(FIRST, FIRST), (FIRST, SECOND, THIRD, FOREIGN)]
)
def test_corrupt_candidate_sets_cannot_be_turned_into_saved_history(candidates):
    with pytest.raises(ValueError, match="INVALID_REPORT_CANDIDATES"):
        exploration_choice(candidates, None, "沒有適合的")
