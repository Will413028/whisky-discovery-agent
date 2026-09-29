"""External control records are immutable, minimal, and independently readable."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from whisky.modules.control.journal import (
    ControlJournalConflict,
    MemoryControlJournal,
    intent_record,
    result_record,
    write_verified,
)
from whisky.modules.control.store import ControlReceipt, control_payload_hash
from whisky.modules.discovery.conditions import ResearchConditions


def receipt(status="effect_applied"):
    return ControlReceipt(
        id=uuid4(),
        owner_id=uuid4(),
        generation=3,
        kind="plan.delete",
        target_id=uuid4(),
        target_generation=3,
        expected_revision=0,
        key=str(uuid4()),
        payload_hash="a" * 64,
        status=status,
        result={"outcome": "completed", "effectAt": "2026-09-29T00:00:00+00:00"},
        created_at=datetime(2026, 9, 29, tzinfo=UTC),
    )


def test_lost_write_ack_replays_same_intent_without_overwriting():
    journal = MemoryControlJournal()
    command = receipt("pending")
    key, body = intent_record(command)
    journal.fail_after_write = True
    with pytest.raises(OSError, match="ack lost"):
        write_verified(journal, key, body)
    journal.fail_after_write = False
    write_verified(journal, key, body)
    assert journal.read(key) == body
    with pytest.raises(ControlJournalConflict):
        write_verified(journal, key, body + b"different")


def test_result_can_be_reconciled_without_reading_intent():
    journal = MemoryControlJournal()
    command = receipt()
    key, body = result_record(command)
    write_verified(journal, key, body)
    assert journal.read(key) == body
    assert command.owner_id.hex.encode() in body
    assert command.target_id.hex.encode() in body
    assert b"effectAt" in body
    assert b"payloadHash" in body


def test_condition_change_records_replayable_key_and_conditions_in_each_object():
    conditions = ResearchConditions(entry="beginner", goal="改走花香", budget_twd=2500)
    pending = replace(
        receipt("pending"),
        kind="plan.change_conditions",
        expected_revision=2,
        new_conditions=conditions,
    )
    result = replace(pending, status="effect_applied")
    for record in (
        json.loads(intent_record(pending)[1]),
        json.loads(result_record(result)[1]),
    ):
        assert record["commandKey"] == pending.key
        assert record["newConditions"] == conditions.model_dump(mode="json")


def test_v1_control_rejects_future_conditions_before_hashing():
    class FutureConditions:
        def canonical_json(self):
            return '{"schema_version":2}'

    with pytest.raises(ValueError, match="v1"):
        control_payload_hash("plan.change_conditions", uuid4(), 1, FutureConditions())
