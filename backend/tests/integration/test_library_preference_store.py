from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from test_comparison_reports_v4 import comparison_commit as comparison_commit
from test_library_conclusions import completed_choice as completed_choice

from whisky.modules.library.contracts import (
    LongTermPreferenceV1,
    SaveBottleFeedbackV1,
    SaveLongTermPreferencesV1,
)
from whisky.modules.library.preference_store import PreferenceStore
from whisky.modules.library.store import LibraryConflict, LibraryStore

pytestmark = pytest.mark.integration


def command():
    return SaveLongTermPreferencesV1(
        key="explicit-preference",
        expected_revision=0,
        preferences=(
            LongTermPreferenceV1(
                description="果香",
                intent="prefer",
                strength="soft",
                statement="我明確表示喜歡果香",
            ),
        ),
    )


def test_explicit_account_preferences_save_and_replay_atomically(completed_choice):
    engine, actor, _, _ = completed_choice
    store = PreferenceStore(engine)
    value = command()
    saved = store.save(actor.id, actor.generation, value)
    assert saved is not None and saved.revision == 1
    assert saved.preferences == value.preferences
    assert store.save(actor.id, actor.generation, value) == saved
    assert store.read(actor.id) == saved


def test_an_active_actor_without_preferences_gets_an_explicit_empty_revision(
    completed_choice,
):
    engine, actor, _, _ = completed_choice
    value = PreferenceStore(engine).read(actor.id)
    assert value is not None and value.revision == 0 and value.preferences == ()
    assert PreferenceStore(engine).read(uuid4()) is None


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("revision", "REVISION_CONFLICT"),
        ("generation", "IDENTITY_CHANGED"),
        ("foreign_feedback", "NOT_FOUND"),
    ],
)
def test_invalid_preference_write_never_becomes_a_saved_profile(
    completed_choice, mutation, code
):
    engine, actor, _, _ = completed_choice
    value = command()
    generation = actor.generation
    if mutation == "revision":
        value = value.model_copy(update={"expected_revision": 1})
    elif mutation == "generation":
        generation += 1
    else:
        value = SaveLongTermPreferencesV1(
            key=value.key,
            expected_revision=0,
            preferences=(
                value.preferences[0].model_copy(
                    update={
                        "source_feedback_id": uuid4(),
                        "source_feedback_revision": 1,
                    }
                ),
            ),
        )
    with pytest.raises(LibraryConflict, match=code):
        PreferenceStore(engine).save(actor.id, generation, value)


def test_preference_revisions_clear_only_the_profile_and_keep_receipt_identity(
    completed_choice,
):
    engine, actor, _, _ = completed_choice
    store = PreferenceStore(engine)
    first = command()
    saved = store.save(actor.id, actor.generation, first)
    changed = store.save(
        actor.id,
        actor.generation,
        SaveLongTermPreferencesV1(key="clear", expected_revision=1, preferences=()),
    )
    assert changed.revision == 2 and changed.preferences == ()
    assert store.read(actor.id) == changed
    assert store.save(actor.id, actor.generation, first) == saved
    with pytest.raises(LibraryConflict, match="IDEMPOTENCY_CONFLICT"):
        store.save(
            actor.id, actor.generation, first.model_copy(update={"preferences": ()})
        )
    with pytest.raises(LibraryConflict, match="REVISION_CONFLICT"):
        store.save(
            actor.id, actor.generation, first.model_copy(update={"key": "stale"})
        )


def test_concurrent_profile_cas_accepts_only_one_revision(completed_choice):
    engine, actor, _, _ = completed_choice
    store = PreferenceStore(engine)
    base = command()
    store.save(actor.id, actor.generation, base)

    def write(key):
        try:
            return store.save(
                actor.id,
                actor.generation,
                base.model_copy(update={"key": key, "expected_revision": 1}),
            ).revision
        except LibraryConflict as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ["first", "second"]))
    assert sorted(map(str, results)) == ["2", "REVISION_CONFLICT"]


def test_failed_receipt_rolls_back_the_profile_effect(completed_choice):
    engine, actor, _, _ = completed_choice

    def fail(connection, cursor, statement, parameters, context, executemany):
        if "INSERT INTO library_commands" in statement:
            raise RuntimeError("injected receipt failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected receipt"):
            PreferenceStore(engine).save(actor.id, actor.generation, command())
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM library_preferences WHERE owner_id=:owner"),
                dict(owner=actor.id),
            )
            == 0
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM library_commands "
                    "WHERE owner_id=:owner AND scope='preferences.save'"
                ),
                dict(owner=actor.id),
            )
            == 0
        )


def test_feedback_provenance_is_owned_revision_fenced_and_never_infers_tags(
    completed_choice,
):
    engine, actor, _, choice = completed_choice
    feedback_command = SaveBottleFeedbackV1(
        key="taste",
        bottle_version_id=choice.selected_version_id,
        expected_revision=0,
        want_to_explore=False,
        tasting="liked",
        tasting_reason="我喜歡果香，但不喜歡橡木",
    )
    feedback = LibraryStore(engine).save_bottle_feedback(
        actor.id, actor.generation, feedback_command
    )
    value = command()
    value = SaveLongTermPreferencesV1(
        key=value.key,
        expected_revision=0,
        preferences=(
            value.preferences[0].model_copy(
                update={
                    "source_feedback_id": feedback.id,
                    "source_feedback_revision": feedback.revision,
                }
            ),
        ),
    )
    saved = PreferenceStore(engine).save(actor.id, actor.generation, value)
    assert len(saved.preferences) == 1 and saved.preferences[0].description == "果香"
    LibraryStore(engine).save_bottle_feedback(
        actor.id,
        actor.generation,
        feedback_command.model_copy(
            update={
                "key": "changed-tasting",
                "expected_revision": 1,
                "tasting": "disliked",
            }
        ),
    )
    with pytest.raises(LibraryConflict, match="SOURCE_FEEDBACK_CHANGED"):
        PreferenceStore(engine).save(
            actor.id,
            actor.generation,
            value.model_copy(update={"key": "new-profile", "expected_revision": 1}),
        )


def test_old_generation_profile_and_receipt_do_not_reappear_after_disable(
    completed_choice,
):
    engine, actor, _, _ = completed_choice
    store = PreferenceStore(engine)
    value = command()
    store.save(actor.id, actor.generation, value)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE users SET active=false,generation=generation+1 WHERE id=:id"),
            dict(id=actor.id),
        )
    assert store.read(actor.id) is None
    with pytest.raises(LibraryConflict, match="IDENTITY_CHANGED"):
        store.save(actor.id, actor.generation, value)
