import json
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from test_comparison_reports_v4 import comparison_commit as comparison_commit
from test_library_conclusions import completed_choice as completed_choice

from whisky.modules.control.store import ControlStore
from whisky.modules.discovery.public import ResearchConditionsV1
from whisky.modules.library.contracts import (
    LongTermPreferenceV1,
    SaveBottleFeedbackV1,
    SaveLongTermPreferencesV1,
)
from whisky.modules.library.export_store import AccountExportStore, ExportUnavailable
from whisky.modules.library.preference_store import PreferenceStore
from whisky.modules.library.store import LibraryStore

pytestmark = pytest.mark.integration


def populate(completed_choice):
    engine, actor, _, choice = completed_choice
    LibraryStore(engine).save_conclusion(actor.id, actor.generation, choice)
    feedback = LibraryStore(engine).save_bottle_feedback(
        actor.id,
        actor.generation,
        SaveBottleFeedbackV1(
            key="export-feedback",
            bottle_version_id=choice.selected_version_id,
            expected_revision=0,
            want_to_explore=True,
            tasting="not_tasted",
            tasting_reason="",
        ),
    )
    PreferenceStore(engine).save(
        actor.id,
        actor.generation,
        SaveLongTermPreferencesV1(
            key="export-preference",
            expected_revision=0,
            preferences=(
                LongTermPreferenceV1(
                    description="果香",
                    intent="prefer",
                    strength="hard",
                    statement="我明確要求果香",
                ),
            ),
        ),
    )
    return engine, actor, feedback


def test_export_keeps_feedback_preferences_and_standalone_historical_evidence(
    completed_choice,
):
    engine, actor, feedback = populate(completed_choice)
    value = json.loads(AccountExportStore(engine).read(actor.id, actor.generation))
    assert value["ownerId"] == str(actor.id)
    assert value["data"]["feedback"][0]["id"] == str(feedback.id)
    assert value["data"]["preferences"][0]["preferences"][0]["strength"] == "hard"
    assert value["data"]["catalogItems"]
    assert value["data"]["catalogPrices"]
    assert all(row["url"] for row in value["data"]["catalogEvidence"])
    assert "workflow_id" not in value["data"]["tasks"][0]


@pytest.mark.parametrize("mutation", ["foreign", "generation", "disabled"])
def test_export_never_exposes_an_ineligible_actor_snapshot(completed_choice, mutation):
    engine, actor, _ = populate(completed_choice)
    owner, generation = actor.id, actor.generation
    if mutation == "foreign":
        owner = uuid4()
    elif mutation == "generation":
        generation += 1
    else:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE users SET active=false,generation=generation+1 WHERE id=:id"
                ),
                dict(id=actor.id),
            )
    with pytest.raises(ExportUnavailable, match="IDENTITY_CHANGED"):
        AccountExportStore(engine).read(owner, generation)


def test_over_limit_export_rejects_instead_of_returning_partial_data(completed_choice):
    engine, actor, _ = populate(completed_choice)
    with pytest.raises(ExportUnavailable, match="EXPORT_TOO_LARGE"):
        AccountExportStore(engine, max_bytes=200).read(actor.id, actor.generation)


def test_preparation_deadline_rejects_and_closes_the_partial_file(
    completed_choice, monkeypatch
):
    import whisky.modules.library.export_store as module

    engine, actor, _ = populate(completed_choice)
    files = []
    original = module.ExportFileWriter

    def capture(*args, **kwargs):
        writer = original(*args, **kwargs)
        files.append(writer.file)
        return writer

    monkeypatch.setattr(module, "ExportFileWriter", capture)
    monkeypatch.setattr(module, "MAX_EXPORT_SECONDS", 0, raising=False)
    try:
        with pytest.raises(ExportUnavailable, match="EXPORT_TIMEOUT"):
            AccountExportStore(engine).prepare(actor.id, actor.generation)
        assert files and all(file.closed for file in files)
    finally:
        for file in files:
            file.close()


def test_deadline_expiring_after_the_last_row_still_rejects_the_export(
    completed_choice, monkeypatch
):
    import whisky.modules.library.export_store as module

    engine, actor, _ = populate(completed_choice)
    elapsed = 0
    original = module.export_references

    def references(*args, **kwargs):
        nonlocal elapsed
        yield from original(*args, **kwargs)
        elapsed = module.MAX_EXPORT_SECONDS + 1

    monkeypatch.setattr(module, "monotonic", lambda: elapsed)
    monkeypatch.setattr(module, "export_references", references)
    # Remove independent rows, so the remaining queries all return zero rows.
    with engine.begin() as connection:
        for table in (
            "library_commands",
            "library_conclusions",
            "library_bottle_feedback",
            "library_preferences",
        ):
            connection.execute(
                text(f"DELETE FROM {table} WHERE owner_id=:owner"),
                dict(owner=actor.id),
            )
    with pytest.raises(ExportUnavailable, match="EXPORT_TIMEOUT"):
        AccountExportStore(engine).prepare(actor.id, actor.generation)


def test_deadline_expiring_during_finish_closes_the_complete_file(
    completed_choice, monkeypatch
):
    import whisky.modules.library.export_store as module

    engine, actor, _ = populate(completed_choice)
    elapsed = 0
    files = []
    original = module.ExportFileWriter.finish

    def finish(writer):
        nonlocal elapsed
        prepared = original(writer)
        files.append(prepared.file)
        elapsed = module.MAX_EXPORT_SECONDS + 1
        return prepared

    monkeypatch.setattr(module, "monotonic", lambda: elapsed)
    monkeypatch.setattr(module.ExportFileWriter, "finish", finish)
    try:
        with pytest.raises(ExportUnavailable, match="EXPORT_TIMEOUT"):
            AccountExportStore(engine).prepare(actor.id, actor.generation)
        assert files and all(file.closed for file in files)
    finally:
        for file in files:
            file.close()


def test_deleted_plan_does_not_reappear_inside_account_export(completed_choice):
    engine, actor, _ = populate(completed_choice)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE plans SET deleted_at=now() WHERE owner_id=:owner"),
            dict(owner=actor.id),
        )
    value = json.loads(AccountExportStore(engine).read(actor.id, actor.generation))
    for section in (
        "plans",
        "tasks",
        "reports",
        "conclusions",
        "reportClaims",
        "catalogEvidence",
    ):
        assert value["data"][section] == []
    assert value["data"]["feedback"] and value["data"]["preferences"]


def test_export_includes_retained_preference_history_after_profile_is_cleared(
    completed_choice,
):
    engine, actor, _ = populate(completed_choice)
    PreferenceStore(engine).save(
        actor.id,
        actor.generation,
        SaveLongTermPreferencesV1(
            key="clear-before-export", expected_revision=1, preferences=()
        ),
    )
    value = json.loads(AccountExportStore(engine).read(actor.id, actor.generation))
    assert value["data"]["preferences"][0]["preferences"] == []
    historical = [
        row
        for row in value["data"]["libraryHistory"]
        if row["scope"] == "preferences.save"
    ]
    assert len(historical) == 2
    assert historical[0]["response"]["preferences"][0]["statement"] == "我明確要求果香"
    assert "payload_hash" not in historical[0] and "key" not in historical[0]


def test_retained_condition_change_is_exported_with_its_actual_status(completed_choice):
    engine, actor, _ = populate(completed_choice)
    _, _, _, choice = completed_choice
    proposed = ResearchConditionsV1.model_validate(
        {
            "schema_version": 1,
            "entry": "beginner",
            "goal": "合成歷史條件修改",
            "budget_twd": "950",
            "preferences": [],
        }
    )
    receipt = ControlStore(engine).reserve(
        actor.id,
        actor.generation,
        "plan.change_conditions",
        choice.plan_id,
        str(uuid4()),
        expected_revision=1,
        conditions=proposed,
    )
    value = json.loads(AccountExportStore(engine).read(actor.id, actor.generation))
    row = value["data"]["conditionChanges"][0]
    assert row["id"] == str(receipt.id)
    assert row["status"] == "pending"
    assert row["new_conditions"]["goal"] == "合成歷史條件修改"
    assert "payload_hash" not in row and "key" not in row


def test_export_sections_share_one_snapshot_when_a_later_record_changes(
    completed_choice,
):
    engine, actor, feedback = populate(completed_choice)
    changed = False

    def change_after_first_query(
        connection, cursor, statement, parameters, context, many
    ):
        nonlocal changed
        if changed or "FROM plans WHERE owner_id" not in statement:
            return
        changed = True
        with engine.begin() as writer:
            writer.execute(
                text("""
                    UPDATE library_bottle_feedback SET revision=revision+1,
                        tasting='liked',tasting_reason='快照開始後才修改'
                    WHERE id=:id
                """),
                dict(id=feedback.id),
            )

    event.listen(engine, "before_cursor_execute", change_after_first_query)
    try:
        value = json.loads(AccountExportStore(engine).read(actor.id, actor.generation))
    finally:
        event.remove(engine, "before_cursor_execute", change_after_first_query)
    assert changed
    assert value["data"]["feedback"][0]["tasting"] == "not_tasted"
    assert (
        LibraryStore(engine)
        .read_bottle_feedback(actor.id, feedback.bottle_version_id)
        .tasting
        == "liked"
    )
