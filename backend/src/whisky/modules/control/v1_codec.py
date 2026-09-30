"""Frozen schemaVersion=1 control payload codec and digest."""

import json
from hashlib import sha256
from uuid import UUID

from whisky.modules.discovery.public import ResearchConditionsV1


def decode_conditions_v1(raw: object) -> ResearchConditionsV1:
    """Do not parse old external records with the current conditions schema."""
    return ResearchConditionsV1.model_validate(raw)


def payload_hash_v1(
    kind: str,
    target_id: UUID,
    expected_revision: int,
    conditions: ResearchConditionsV1 | None,
) -> str:
    payload = json.dumps(
        dict(
            kind=kind,
            targetId=str(target_id),
            expectedRevision=expected_revision,
            conditions=json.loads(conditions.canonical_json()) if conditions else None,
        ),
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode()).hexdigest()
