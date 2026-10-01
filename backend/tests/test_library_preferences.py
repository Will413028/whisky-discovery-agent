import pytest

from whisky.modules.library.preferences import StatedPreference, stated_preferences


def test_long_term_preferences_only_store_an_explicit_statement_without_budget():
    value = StatedPreference("果香", "prefer", "soft", "我明確表示喜歡果香")
    assert stated_preferences((value,)) == (value,)
    assert not hasattr(value, "budget_twd")


@pytest.mark.parametrize(
    "values",
    [
        (StatedPreference("", "prefer", "soft", "我喜歡"),),
        (StatedPreference("果香", "prefer", "soft", ""),),
        (
            StatedPreference("果香", "prefer", "soft", "我喜歡果香"),
            StatedPreference("果香", "avoid", "hard", "我不喜歡果香"),
        ),
        tuple(
            StatedPreference(str(index), "prefer", "soft", "明述")
            for index in range(65)
        ),
    ],
)
def test_invalid_or_ambiguous_long_term_preferences_are_rejected(values):
    with pytest.raises(ValueError):
        stated_preferences(values)
