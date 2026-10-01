import pytest

from whisky.modules.library.feedback import bottle_feedback


def test_wanting_to_explore_is_independent_of_tasting_and_liking():
    favorite = bottle_feedback(True, "not_tasted")
    assert favorite is not None, "an explicit favorite must be represented separately"
    assert favorite.want_to_explore and favorite.tasting == "not_tasted"
    disliked = bottle_feedback(True, "disliked", "煙燻不合這次心情")
    assert disliked is not None
    assert disliked.want_to_explore and disliked.tasting == "disliked"
    assert disliked.tasting_reason == "煙燻不合這次心情"
    liked = bottle_feedback(False, "liked", "這支喝起來喜歡")
    assert liked is not None and not liked.want_to_explore
    assert liked.tasting == "liked"
    assert not hasattr(liked, "preferences"), (
        "liking a bottle cannot silently confirm every flavor tag"
    )


@pytest.mark.parametrize("reason", ["未喝過卻留下喜歡理由", "a" * 2001])
def test_invalid_tasting_reason_cannot_become_feedback(reason):
    with pytest.raises(ValueError):
        bottle_feedback(True, "not_tasted", reason)
