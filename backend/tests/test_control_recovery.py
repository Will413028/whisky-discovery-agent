"""External control records must be completely read before reconciliation."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from whisky.modules.control.journal import (
    MemoryControlJournal,
    intent_record,
    result_record,
)
from whisky.modules.control.recovery import (
    ListingPage,
    RecoveryError,
    read_complete_control_log,
)
from whisky.modules.control.store import ControlReceipt, control_payload_hash


class PagedJournal(MemoryControlJournal):
    def __init__(self, page_size: int = 1) -> None:
        super().__init__()
        self.page_size = page_size
        self.page_calls = 0
        self.fail_on_page: int | None = None

    def list_page(self, prefix: str, start: str | None) -> ListingPage:
        self.page_calls += 1
        if self.page_calls == self.fail_on_page:
            raise OSError("list page unavailable")
        names = [
            name
            for name in sorted(self.objects)
            if name.startswith(prefix) and (start is None or name >= start)
        ]
        return ListingPage(
            tuple(names[: self.page_size]),
            names[self.page_size] if len(names) > self.page_size else None,
        )


def _command(created_at: datetime) -> ControlReceipt:
    target = uuid4()
    return ControlReceipt(
        id=uuid4(),
        owner_id=uuid4(),
        generation=1,
        kind="task.cancel",
        target_id=target,
        target_generation=1,
        expected_revision=0,
        key=str(uuid4()),
        payload_hash=control_payload_hash("task.cancel", target, 0, None),
        status="pending",
        result=None,
        created_at=created_at,
    )


def _put_intent(journal: PagedJournal, command: ControlReceipt) -> None:
    key, body = intent_record(command)
    journal.put_once(key, body)


def _put_result(journal: PagedJournal, command: ControlReceipt) -> None:
    key, body = result_record(command)
    journal.put_once(key, body)


def test_reads_every_page_and_keeps_an_intent_older_than_30_days():
    journal = PagedJournal(page_size=1)
    old = _command(datetime.now(UTC) - timedelta(days=45))
    finished = _command(datetime.now(UTC))
    _put_intent(journal, old)
    _put_intent(journal, finished)
    _put_result(
        journal,
        replace(
            finished,
            status="effect_applied",
            result={"outcome": "completed", "effectAt": datetime.now(UTC).isoformat()},
        ),
    )

    commands = read_complete_control_log(journal)
    assert {command.id for command in commands} == {old.id, finished.id}
    assert {command.id: command.status for command in commands} == {
        old.id: "intent_confirmed",
        finished.id: "completed",
    }
    assert journal.page_calls == 3


def test_unreadable_later_page_fails_closed():
    journal = PagedJournal(page_size=1)
    _put_intent(journal, _command(datetime.now(UTC)))
    _put_intent(journal, _command(datetime.now(UTC)))
    journal.fail_on_page = 2
    with pytest.raises(RecoveryError, match="list"):
        read_complete_control_log(journal)


def test_result_without_intent_or_mismatched_payload_fails_closed():
    journal = PagedJournal()
    command = _command(datetime.now(UTC))
    _put_result(
        journal,
        replace(
            command,
            status="effect_rejected",
            result={
                "outcome": "rejected",
                "code": "REVISION_CONFLICT",
                "effectAt": datetime.now(UTC).isoformat(),
            },
        ),
    )
    with pytest.raises(RecoveryError, match="intent"):
        read_complete_control_log(journal)

    _put_intent(journal, command)
    key, body = intent_record(command)
    altered = json.loads(body)
    altered["targetId"] = uuid4().hex
    journal.objects[key] = json.dumps(altered).encode()
    with pytest.raises(RecoveryError, match="payload"):
        read_complete_control_log(journal)


def test_repeated_listing_token_fails_closed():
    class RepeatingJournal(PagedJournal):
        def list_page(self, prefix: str, start: str | None) -> ListingPage:
            return ListingPage((), "controls/repeated")

    with pytest.raises(RecoveryError, match="pagination"):
        read_complete_control_log(RepeatingJournal())


def test_bool_schema_version_and_wrong_actor_delete_target_fail_closed():
    journal = PagedJournal()
    command = _command(datetime.now(UTC))
    key, body = intent_record(command)
    record = json.loads(body)
    record["schemaVersion"] = True
    journal.objects[key] = json.dumps(record).encode()
    with pytest.raises(RecoveryError, match="schema"):
        read_complete_control_log(journal)

    record["schemaVersion"] = 1
    record["kind"] = "actor.delete"
    record["payloadHash"] = control_payload_hash(
        "actor.delete", command.target_id, 0, None
    )
    journal.objects[key] = json.dumps(record).encode()
    with pytest.raises(RecoveryError, match="target"):
        read_complete_control_log(journal)


def test_endless_empty_pages_fail_with_a_bound():
    class EndlessJournal(PagedJournal):
        def list_page(self, prefix: str, start: str | None) -> ListingPage:
            self.page_calls += 1
            if self.page_calls > 2000:
                raise OSError("unbounded listing")
            return ListingPage((), f"controls/{self.page_calls:08x}")

    with pytest.raises(RecoveryError, match="pagination bound"):
        read_complete_control_log(EndlessJournal())


def test_v1_external_conditions_remain_decodable_when_current_model_changes(
    monkeypatch,
):
    from whisky.modules.discovery import conditions as current_conditions

    journal = PagedJournal()
    command = replace(
        _command(datetime.now(UTC)),
        kind="plan.change_conditions",
        expected_revision=1,
        new_conditions=current_conditions.ResearchConditions(
            entry="beginner", goal="舊版條件", budget_twd=2500
        ),
    )
    command = replace(
        command,
        payload_hash=control_payload_hash(
            command.kind, command.target_id, 1, command.new_conditions
        ),
    )
    _put_intent(journal, command)

    class FutureConditions:
        @classmethod
        def model_validate(cls, value):
            raise ValueError("v2 no longer parses v1")

    # A future current schema must not redefine the persisted v1 wire codec.
    monkeypatch.setattr(current_conditions, "ResearchConditions", FutureConditions)
    monkeypatch.setattr(
        __import__("whisky.modules.control.recovery", fromlist=["ResearchConditions"]),
        "ResearchConditions",
        FutureConditions,
        raising=False,
    )
    recovered = read_complete_control_log(journal)
    assert recovered[0].new_conditions == command.new_conditions


def test_independent_witness_detects_an_entire_missing_command_pair():
    primary = PagedJournal()
    witness = PagedJournal()
    command = _command(datetime.now(UTC))
    completed = replace(
        command,
        status="effect_applied",
        result={"outcome": "completed", "effectAt": datetime.now(UTC).isoformat()},
    )
    for journal in (primary, witness):
        _put_intent(journal, command)
        _put_result(journal, completed)
    primary.objects.clear()

    with pytest.raises(RecoveryError, match="witness"):
        read_complete_control_log(primary, witness)


def test_isolated_recovery_repairs_a_valid_witness_only_intent():
    from whisky.modules.control.recovery import repair_witness_only

    primary = PagedJournal()
    witness = PagedJournal()
    command = _command(datetime.now(UTC))
    _put_intent(witness, command)

    assert repair_witness_only(primary, witness) == 1
    assert read_complete_control_log(primary, witness)[0].id == command.id
    assert repair_witness_only(primary, witness) == 0


def test_isolated_recovery_never_reconstructs_a_missing_witness():
    from whisky.modules.control.recovery import repair_witness_only

    primary = PagedJournal()
    witness = PagedJournal()
    _put_intent(primary, _command(datetime.now(UTC)))

    with pytest.raises(RecoveryError, match="primary-only"):
        repair_witness_only(primary, witness)
    assert witness.objects == {}
