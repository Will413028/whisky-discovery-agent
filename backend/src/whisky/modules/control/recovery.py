"""Read the complete external control log before opening restored private data."""

import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import Connection, text

from whisky.modules.control.journal import (
    ControlJournal,
    result_record,
    write_verified,
)
from whisky.modules.control.store import (
    ControlKind,
    ControlReceipt,
    ControlStatus,
    ControlStore,
)
from whisky.modules.control.v1_codec import decode_conditions_v1, payload_hash_v1
from whisky.modules.discovery.public import (
    actor_plans_closed,
    plan_control_effect_present,
)
from whisky.modules.identity.public import control_actor_state
from whisky.modules.library.public import purge_actor_library, purge_plan_library
from whisky.modules.research.public import (
    actor_tasks_closed,
    close_actor_tasks,
    close_plan_tasks,
    plan_tasks_closed,
    purge_actor_research,
    purge_plan_research,
    task_control_effect_present,
)
from whisky.platform.domain_errors import DomainRejection

CONTROL_PREFIX = "controls/"
CONTROL_KEY = re.compile(r"controls/([0-9a-f]{32})/(intent|result)\.json\Z")
MAX_CONTROL_OBJECTS = 100_000
MAX_CONTROL_PAGES = 2_000
MAX_CONTROL_RECORD_BYTES = 65_536
RECORD_FIELDS = frozenset(
    {
        "schemaVersion",
        "commandId",
        "ownerId",
        "kind",
        "targetId",
        "targetGeneration",
        "expectedRevision",
        "commandKey",
        "payloadHash",
        "newConditions",
        "recordType",
    }
)


class RecoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ListingPage:
    keys: tuple[str, ...]
    next_start: str | None


class ControlRecoveryJournal(ControlJournal, Protocol):
    def list_page(self, prefix: str, start: str | None) -> ListingPage: ...


def repair_witness_only(
    primary: ControlRecoveryJournal, witness: ControlRecoveryJournal
) -> int:
    """In isolated mode, complete a crash between witness and primary PUTs.

    The witness is fully parsed before any repair. Primary-only keys and body
    disagreement stay isolated; neither can be guessed from the other side.
    """
    read_complete_control_log(witness)
    primary_keys = set(_list_all_keys(primary))
    witness_keys = set(_list_all_keys(witness))
    if primary_keys - witness_keys:
        raise RecoveryError("control primary-only record has no witness")
    for key in sorted(primary_keys):
        try:
            if primary.read(key) != witness.read(key):
                raise RecoveryError("control witness body differs")
        except RecoveryError:
            raise
        except Exception as error:
            raise RecoveryError("control repair read failed") from error
    missing = sorted(witness_keys - primary_keys)
    for key in missing:
        try:
            write_verified(primary, key, witness.read(key))
        except Exception as error:
            raise RecoveryError("control witness repair failed") from error
    read_complete_control_log(primary, witness)
    return len(missing)


def read_complete_control_log(
    journal: ControlRecoveryJournal,
    witness: ControlRecoveryJournal | None = None,
) -> tuple[ControlReceipt, ...]:
    """List every page, fetch every object, then validate all command pairs."""
    keys = _list_all_keys(journal)
    if witness is not None:
        try:
            witness_keys = _list_all_keys(witness)
        except RecoveryError as error:
            raise RecoveryError("control witness list failed") from error
        if keys != witness_keys:
            raise RecoveryError("control witness inventory differs")
    bodies: dict[UUID, dict[str, dict[str, object]]] = {}
    for key in keys:
        match = CONTROL_KEY.fullmatch(key)
        assert match is not None
        identifier, part = UUID(hex=match.group(1)), match.group(2)
        try:
            body = journal.read(key)
        except Exception as error:
            raise RecoveryError("control read failed") from error
        if witness is not None:
            try:
                witnessed = witness.read(key)
            except Exception as error:
                raise RecoveryError("control witness read failed") from error
            if witnessed != body:
                raise RecoveryError("control witness body differs")
        if len(body) > MAX_CONTROL_RECORD_BYTES:
            raise RecoveryError("control record exceeds bound")
        try:
            record = json.loads(body)
        except (ValueError, UnicodeDecodeError) as error:
            raise RecoveryError("control record is not JSON") from error
        if not isinstance(record, dict):
            raise RecoveryError("control record is not an object")
        if (
            record.get("recordType") != part
            or record.get("commandId") != identifier.hex
        ):
            raise RecoveryError("control record key and payload disagree")
        bodies.setdefault(identifier, {})[part] = record

    commands = []
    for identifier, parts in bodies.items():
        intent = parts.get("intent")
        if intent is None:
            raise RecoveryError("control result has no intent")
        receipt = _parse_intent(identifier, intent)
        result = parts.get("result")
        if result is not None:
            receipt = _parse_result(receipt, intent, result)
        commands.append(receipt)
    return tuple(sorted(commands, key=lambda item: (item.created_at, item.id.hex)))


def reconcile_control_log(
    journal: ControlRecoveryJournal,
    store: ControlStore,
    witness: ControlRecoveryJournal | None = None,
) -> tuple[ControlReceipt, ...]:
    """Keep the API offline until every outside command has been reconciled."""
    commands = read_complete_control_log(journal, witness)
    outside_ids = {command.id for command in commands}
    with store.engine.connect() as connection:
        durable_ids: set[UUID] = set(
            connection.execute(
                text("SELECT id FROM control_commands WHERE status <> 'pending'")
            ).scalars()
        )
    if durable_ids - outside_ids:
        raise RecoveryError("control receipt is missing outside records")
    # A result timestamp is an observation, not a causal clock. A successful
    # task cancellation must precede a plan fence, successive condition edits
    # follow their expected revisions, and actor deletion comes last.
    action_rank = {
        "task.cancel": 0,
        "plan.change_conditions": 1,
        "plan.delete": 2,
        "actor.delete": 3,
    }
    successful: set[tuple[UUID, int, str, UUID, int]] = set()
    for command in commands:
        if command.status != "completed":
            continue
        position = (
            command.owner_id,
            command.generation,
            command.kind,
            command.target_id,
            command.expected_revision,
        )
        if position in successful:
            raise RecoveryError("duplicate completed control position")
        successful.add(position)
    ordered = sorted(
        commands,
        key=lambda item: (
            item.owner_id.hex,
            item.generation,
            {"completed": 0, "rejected": 1, "intent_confirmed": 2}[item.status],
            action_rank[item.kind],
            item.target_id.hex,
            item.expected_revision,
            item.created_at,
            item.id.hex,
        ),
    )
    restored: dict[UUID, ControlReceipt] = {}
    for external in ordered:
        receipt = _restore_one(store, external)
        if receipt is None:
            restored[external.id] = external
            continue
        if external.status == "intent_confirmed":
            if receipt.status not in {"effect_applied", "effect_rejected"}:
                raise RecoveryError("pending control did not reach a durable effect")
            try:
                result = result_record(receipt)
                if witness is not None:
                    write_verified(witness, *result)
                write_verified(journal, *result)
            except Exception as error:
                raise RecoveryError("control result write failed") from error
            receipt = store.confirm_result(receipt.id)
        restored[external.id] = receipt
    return tuple(restored[command.id] for command in commands)


def _purge_beneath_completed_delete(
    connection: Connection, command: ControlReceipt, actor: tuple[int, bool]
) -> None:
    """Reapply child fences and cleanup beneath a surviving parent fence."""
    if command.status != "completed":
        return
    owner, generation, target = (
        command.owner_id,
        command.generation,
        command.target_id,
    )
    if command.kind == "actor.delete":
        if (
            actor[0] > generation or actor == (generation, False)
        ) and actor_plans_closed(connection, owner, generation):
            close_actor_tasks(connection, owner, generation)
            purge_actor_library(connection, owner, generation)
            purge_actor_research(connection, owner, generation)
    elif command.kind == "plan.delete" and plan_control_effect_present(
        connection,
        target,
        owner,
        generation,
        deleted=True,
        expected_revision=command.expected_revision,
        new_conditions=None,
    ):
        close_plan_tasks(connection, owner, target, status="cancelled")
        purge_plan_library(connection, owner, generation, target)
        purge_plan_research(connection, owner, generation, target)


def _restore_one(
    store: ControlStore, external: ControlReceipt
) -> ControlReceipt | None:
    try:
        with store.engine.begin() as connection:
            actor = control_actor_state(connection, external.owner_id, lock=True)
            row = (
                connection.execute(
                    text("SELECT * FROM control_commands WHERE id=:id FOR UPDATE"),
                    {"id": external.id},
                )
                .mappings()
                .first()
            )
            if row is not None:
                _match_existing(store._view(row), external)
            if actor is None:
                if row is not None:
                    raise RecoveryError("control receipt has no actor")
                return None
            _purge_beneath_completed_delete(connection, external, actor)
            if actor[0] > external.generation:
                if external.status == "completed" and not _effect_present(
                    connection, external
                ):
                    raise RecoveryError("old-generation control effect is missing")
                if row is not None:
                    current = store._view(row)
                    if external.status == "intent_confirmed" and current.status in {
                        "effect_applied",
                        "effect_rejected",
                    }:
                        if current.status == "effect_applied" and not _effect_present(
                            connection, current
                        ):
                            raise RecoveryError(
                                "old-generation control effect is missing"
                            )
                        return current
                    if (
                        current.status == "effect_applied"
                        and external.status == "completed"
                    ):
                        _match_effect_result(current, external)
                        return _update_status(connection, store, external, "completed")
                    if (
                        current.status == "effect_rejected"
                        and external.status == "rejected"
                    ):
                        _match_effect_result(current, external)
                        return _update_status(connection, store, external, "rejected")
                    _match_final_status(current, external)
                    return current
                return None
            if actor != (external.generation, True) and not (
                external.kind == "actor.delete"
                and external.status == "completed"
                and actor == (external.generation, False)
                and _effect_present(connection, external)
            ):
                raise RecoveryError("control actor generation is inconsistent")
            if row is None:
                collision = connection.scalar(
                    text("""
                    SELECT id FROM control_commands
                    WHERE owner_id=:owner AND kind=:kind AND key=:key
                    """),
                    dict(owner=external.owner_id, kind=external.kind, key=external.key),
                )
                if collision is not None:
                    raise RecoveryError("control command key belongs to another id")
                row = (
                    connection.execute(
                        text("""
                        INSERT INTO control_commands
                            (id,owner_id,generation,kind,target_id,target_generation,
                             expected_revision,key,payload_hash,new_conditions,
                             status,result,created_at)
                        VALUES (:id,:owner,:generation,:kind,:target,:target_generation,
                                :revision,:key,:hash,CAST(:conditions AS jsonb),
                                :status,CAST(:result AS jsonb),:created)
                        RETURNING *
                        """),
                        dict(
                            id=external.id,
                            owner=external.owner_id,
                            generation=external.generation,
                            kind=external.kind,
                            target=external.target_id,
                            target_generation=external.target_generation,
                            revision=external.expected_revision,
                            key=external.key,
                            hash=external.payload_hash,
                            conditions=(
                                external.new_conditions.canonical_json()
                                if external.new_conditions is not None
                                else None
                            ),
                            status=(
                                "rejected"
                                if external.status == "rejected"
                                else "intent_confirmed"
                            ),
                            result=(
                                json.dumps(external.result)
                                if external.status == "rejected"
                                else None
                            ),
                            created=external.created_at,
                        ),
                    )
                    .mappings()
                    .one()
                )
            current = store._view(row)
            if external.status == "rejected":
                if current.status in {"effect_applied", "completed"}:
                    raise RecoveryError(
                        "rejected control conflicts with applied effect"
                    )
                if current.status in {"effect_rejected", "rejected"}:
                    _match_effect_result(current, external)
                return _update_status(connection, store, external, "rejected")
            if external.status == "completed":
                if current.status in {"effect_rejected", "rejected"}:
                    raise RecoveryError("completed control conflicts with rejection")
                if current.status == "effect_applied":
                    _match_effect_result(current, external)
                if current.status == "completed":
                    _match_final_status(current, external)
                    if not _effect_present(connection, external):
                        raise RecoveryError("completed control effect is missing")
                    return current
                if current.status in {"pending", "intent_confirmed"} and not (
                    _effect_present(connection, external)
                ):
                    try:
                        with connection.begin_nested():
                            store._effect(connection, row)
                    except DomainRejection as error:
                        raise RecoveryError(
                            "confirmed control effect could not be restored"
                        ) from error
                if not _effect_present(connection, external):
                    raise RecoveryError("completed control effect is missing")
                return _update_status(connection, store, external, "completed")
            if current.status in {"completed", "rejected"}:
                raise RecoveryError("outside control result is missing")
            if current.status in {"effect_applied", "effect_rejected"}:
                return current
            try:
                with connection.begin_nested():
                    store._effect(connection, row)
            except DomainRejection as error:
                result = dict(
                    outcome="rejected",
                    code=error.code,
                    effectAt=datetime.now(UTC).isoformat(),
                )
                return _update_status(
                    connection,
                    store,
                    replace(external, result=result),
                    "effect_rejected",
                )
            result = dict(outcome="completed", effectAt=datetime.now(UTC).isoformat())
            return _update_status(
                connection, store, replace(external, result=result), "effect_applied"
            )
    except RecoveryError:
        raise
    except Exception as error:
        raise RecoveryError("control DB reconciliation failed") from error


def _match_existing(current: ControlReceipt, external: ControlReceipt) -> None:
    fields = (
        "owner_id",
        "generation",
        "kind",
        "target_id",
        "target_generation",
        "expected_revision",
        "key",
        "payload_hash",
        "created_at",
        "new_conditions",
    )
    if any(getattr(current, field) != getattr(external, field) for field in fields):
        raise RecoveryError("control receipt and outside record disagree")


def _match_final_status(current: ControlReceipt, external: ControlReceipt) -> None:
    if current.status != external.status or current.result != external.result:
        raise RecoveryError("control receipt and outside result disagree")


def _match_effect_result(current: ControlReceipt, external: ControlReceipt) -> None:
    if current.result != external.result:
        raise RecoveryError("control effect and outside result disagree")


def _update_status(
    connection: Connection,
    store: ControlStore,
    external: ControlReceipt,
    status: ControlStatus,
) -> ControlReceipt:
    updated = (
        connection.execute(
            text("""
            UPDATE control_commands
            SET status=:status,result=CAST(:result AS jsonb),updated_at=now()
            WHERE id=:id RETURNING *
            """),
            dict(id=external.id, status=status, result=json.dumps(external.result)),
        )
        .mappings()
        .one()
    )
    return store._view(updated)


def _effect_present(connection: Connection, command: ControlReceipt) -> bool:
    """A restored receipt is insufficient when its DB fence has vanished."""
    owner = command.owner_id
    generation = command.generation
    target = command.target_id
    try:
        if command.kind == "actor.delete":
            actor = control_actor_state(connection, owner)
            return (
                (actor is None or actor[0] > generation)
                and actor_plans_closed(connection, owner, generation)
                and actor_tasks_closed(connection, owner, generation)
            )
        if command.kind == "task.cancel":
            return task_control_effect_present(connection, target, owner, generation)
        return plan_control_effect_present(
            connection,
            target,
            owner,
            generation,
            deleted=command.kind == "plan.delete",
            expected_revision=command.expected_revision,
            new_conditions=command.new_conditions,
        ) and plan_tasks_closed(
            connection,
            target,
            owner,
            generation,
            command.expected_revision
            if command.kind == "plan.change_conditions"
            else None,
        )
    except ValueError as error:
        raise RecoveryError("control target belongs to another scope") from error


def _list_all_keys(journal: ControlRecoveryJournal) -> tuple[str, ...]:
    start: str | None = None
    tokens: set[str] = set()
    keys: list[str] = []
    page_count = 0
    while True:
        if page_count >= MAX_CONTROL_PAGES:
            raise RecoveryError("control pagination bound exceeded")
        page_count += 1
        try:
            page = journal.list_page(CONTROL_PREFIX, start)
        except Exception as error:
            raise RecoveryError("control list failed") from error
        for key in page.keys:
            if (
                CONTROL_KEY.fullmatch(key) is None
                or (start is not None and key < start)
                or (keys and key <= keys[-1])
            ):
                raise RecoveryError("control pagination contains an invalid key")
            keys.append(key)
            if len(keys) > MAX_CONTROL_OBJECTS:
                raise RecoveryError("control listing exceeds bound")
        next_start = page.next_start
        if next_start is None:
            return tuple(keys)
        if (
            not next_start.startswith(CONTROL_PREFIX)
            or (start is not None and next_start <= start)
            or (keys and next_start <= keys[-1])
            or next_start in tokens
        ):
            raise RecoveryError("control pagination did not advance")
        tokens.add(next_start)
        start = next_start


def _hex_uuid(value: object, label: str) -> UUID:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise RecoveryError(f"invalid control {label}")
    return UUID(hex=value)


def _aware_time(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise RecoveryError(f"invalid control {label}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise RecoveryError(f"invalid control {label}") from error
    if parsed.utcoffset() is None:
        raise RecoveryError(f"invalid control {label}")
    return parsed


def _parse_intent(identifier: UUID, record: dict[str, object]) -> ControlReceipt:
    if (
        set(record) != RECORD_FIELDS | {"createdAt"}
        or type(record.get("schemaVersion")) is not int
        or record["schemaVersion"] != 1
    ):
        raise RecoveryError("invalid control intent schema")
    if record.get("recordType") != "intent":
        raise RecoveryError("invalid control intent type")
    owner = _hex_uuid(record.get("ownerId"), "owner")
    target = _hex_uuid(record.get("targetId"), "target")
    kind = record.get("kind")
    if kind not in {
        "task.cancel",
        "plan.change_conditions",
        "plan.delete",
        "actor.delete",
    }:
        raise RecoveryError("invalid control kind")
    if kind == "actor.delete" and target != owner:
        raise RecoveryError("invalid actor-delete target")
    generation = record.get("targetGeneration")
    revision = record.get("expectedRevision")
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation < 1
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 0
    ):
        raise RecoveryError("invalid control generation or revision")
    raw_conditions = record.get("newConditions")
    if kind == "plan.change_conditions":
        if revision < 1 or not isinstance(raw_conditions, dict):
            raise RecoveryError("invalid control conditions")
        try:
            conditions = decode_conditions_v1(raw_conditions)
        except ValueError as error:
            raise RecoveryError("invalid control conditions") from error
    else:
        if revision or raw_conditions is not None:
            raise RecoveryError("unexpected control conditions")
        conditions = None
    raw_key = record.get("commandKey")
    try:
        key = UUID(str(raw_key))
    except ValueError as error:
        raise RecoveryError("invalid control command key") from error
    if key.version != 4 or str(key) != raw_key:
        raise RecoveryError("invalid control command key")
    digest = record.get("payloadHash")
    if (
        not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or digest
        != payload_hash_v1(cast(ControlKind, kind), target, revision, conditions)
    ):
        raise RecoveryError("control payload hash mismatch")
    return ControlReceipt(
        id=identifier,
        owner_id=owner,
        generation=generation,
        kind=cast(ControlKind, kind),
        target_id=target,
        target_generation=generation,
        expected_revision=revision,
        key=str(key),
        payload_hash=digest,
        status="intent_confirmed",
        result=None,
        created_at=_aware_time(record.get("createdAt"), "createdAt"),
        new_conditions=conditions,
    )


def _parse_result(
    receipt: ControlReceipt,
    intent: dict[str, object],
    result: dict[str, object],
) -> ControlReceipt:
    outcome = result.get("outcome")
    fields = RECORD_FIELDS | {"outcome", "effectAt"}
    if outcome == "rejected":
        fields |= {"code"}
    if (
        set(result) != fields
        or type(result.get("schemaVersion")) is not int
        or result["schemaVersion"] != 1
    ):
        raise RecoveryError("invalid control result schema")
    if result.get("recordType") != "result":
        raise RecoveryError("invalid control result type")
    for field in RECORD_FIELDS - {"recordType"}:
        if result[field] != intent[field]:
            raise RecoveryError("control intent and result payload disagree")
    if outcome not in {"completed", "rejected"}:
        raise RecoveryError("invalid control result outcome")
    code = result.get("code")
    if outcome == "rejected" and (not isinstance(code, str) or not code):
        raise RecoveryError("invalid control result code")
    _aware_time(result.get("effectAt"), "effectAt")
    recorded = {
        "outcome": cast(str, outcome),
        "effectAt": cast(str, result["effectAt"]),
    }
    if outcome == "rejected":
        recorded["code"] = cast(str, code)
    return replace(receipt, status=cast(ControlStatus, outcome), result=recorded)
