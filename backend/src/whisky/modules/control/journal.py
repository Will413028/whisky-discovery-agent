"""Minimal, immutable control records outside the product/Temporal cluster."""

import json
from typing import Protocol

from whisky.modules.control.store import ControlReceipt


class ControlJournalConflict(ValueError):
    pass


class ControlJournal(Protocol):
    def put_once(self, key: str, body: bytes) -> None: ...

    def read(self, key: str) -> bytes: ...


def _record(command: ControlReceipt) -> dict[str, object]:
    return dict(
        schemaVersion=1,
        commandId=command.id.hex,
        ownerId=command.owner_id.hex,
        kind=command.kind,
        targetId=command.target_id.hex,
        targetGeneration=command.target_generation,
        expectedRevision=command.expected_revision,
        commandKey=command.key,
        payloadHash=command.payload_hash,
        newConditions=(
            command.new_conditions.model_dump(mode="json")
            if command.new_conditions is not None
            else None
        ),
    )


def _json_bytes(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def intent_record(command: ControlReceipt) -> tuple[str, bytes]:
    """No deleted content or tokens; condition changes retain the new input."""
    return (
        f"controls/{command.id.hex}/intent.json",
        _json_bytes(
            dict(
                **_record(command),
                recordType="intent",
                createdAt=command.created_at.isoformat(),
            )
        ),
    )


def result_record(command: ControlReceipt) -> tuple[str, bytes]:
    """Include enough scope and outcome to reconcile without the intent object."""
    if command.result is None or command.status not in {
        "effect_applied",
        "effect_rejected",
        "completed",
        "rejected",
    }:
        raise ValueError("Control effect has no durable result yet")
    return (
        f"controls/{command.id.hex}/result.json",
        _json_bytes(dict(**_record(command), recordType="result", **command.result)),
    )


def write_verified(journal: ControlJournal, key: str, body: bytes) -> None:
    """A lost acknowledgement may retry, but a conflicting object never changes."""
    journal.put_once(key, body)
    if journal.read(key) != body:
        raise ControlJournalConflict("External control record readback mismatch")


class MemoryControlJournal:
    """Failure-controllable test adapter; never used as production evidence."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_before_write = False
        self.fail_after_write = False
        self.fail_read = False

    def put_once(self, key: str, body: bytes) -> None:
        if self.fail_before_write:
            raise OSError("external control store unavailable")
        existing = self.objects.get(key)
        if existing is not None and existing != body:
            raise ControlJournalConflict("External control record already differs")
        self.objects[key] = body
        if self.fail_after_write:
            raise OSError("ack lost after external write")

    def read(self, key: str) -> bytes:
        if self.fail_read:
            raise OSError("external control record unreadable")
        return self.objects[key]
