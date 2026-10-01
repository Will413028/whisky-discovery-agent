"""Owner-scoped account preferences; an ordinary atomic CRUD transaction."""

import json
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, text

from whisky.modules.identity.public import actor_generation
from whisky.modules.library.contracts import (
    LongTermPreferencesViewV1,
    SaveLongTermPreferencesV1,
)
from whisky.modules.library.store import LibraryConflict


class PreferenceStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def read(self, owner: UUID) -> LongTermPreferencesViewV1 | None:
        with self.engine.connect() as connection:
            generation = actor_generation(connection, owner)
            if generation is None:
                return None
            row = self._row(connection, owner, generation)
            return (
                self._view(row)
                if row
                else LongTermPreferencesViewV1(
                    revision=0, preferences=(), updated_at=None
                )
            )

    def save(
        self, owner: UUID, generation: int, command: SaveLongTermPreferencesV1
    ) -> LongTermPreferencesViewV1:
        digest = sha256(
            json.dumps(
                command.model_dump(mode="json", by_alias=True),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        with self.engine.begin() as connection:
            if actor_generation(connection, owner, lock=True) != generation:
                raise LibraryConflict("IDENTITY_CHANGED")
            existing = self._row(connection, owner, generation)
            prior = connection.execute(
                text("""
                SELECT payload_hash,response FROM library_commands
                WHERE owner_id=:owner AND generation=:generation
                    AND scope='preferences.save' AND key=:key
            """),
                dict(owner=owner, generation=generation, key=command.key),
            ).first()
            if prior is not None:
                if prior.payload_hash != digest:
                    raise LibraryConflict("IDEMPOTENCY_CONFLICT")
                if existing is None:
                    raise LibraryConflict("NOT_FOUND")
                return LongTermPreferencesViewV1.model_validate(prior.response)
            if command.expected_revision != (existing["revision"] if existing else 0):
                raise LibraryConflict("REVISION_CONFLICT")
            for preference in command.preferences:
                if preference.source_feedback_id is None:
                    continue
                feedback = connection.execute(
                    text("""
                    SELECT revision,tasting FROM library_bottle_feedback
                    WHERE id=:id AND owner_id=:owner AND generation=:generation
                """),
                    dict(
                        id=preference.source_feedback_id,
                        owner=owner,
                        generation=generation,
                    ),
                ).first()
                if feedback is None:
                    raise LibraryConflict("NOT_FOUND")
                if (
                    feedback.revision != preference.source_feedback_revision
                    or feedback.tasting == "not_tasted"
                ):
                    raise LibraryConflict("SOURCE_FEEDBACK_CHANGED")
            content = json.dumps(
                [
                    value.model_dump(mode="json", by_alias=True)
                    for value in command.preferences
                ]
            )
            row = (
                connection.execute(
                    text("""
                INSERT INTO library_preferences
                    (owner_id,generation,revision,preferences)
                VALUES (:owner,:generation,1,CAST(:content AS jsonb))
                ON CONFLICT(owner_id,generation) DO UPDATE
                    SET revision=library_preferences.revision+1,
                        preferences=EXCLUDED.preferences,updated_at=now()
                RETURNING *
            """),
                    dict(owner=owner, generation=generation, content=content),
                )
                .mappings()
                .one()
            )
            saved = self._view(row)
            connection.execute(
                text("""
                INSERT INTO library_commands
                    (id,owner_id,generation,scope,key,payload_hash,target_id,response)
                VALUES (:id,:owner,:generation,'preferences.save',:key,:digest,
                    :owner,CAST(:response AS jsonb))
            """),
                dict(
                    id=uuid4(),
                    owner=owner,
                    generation=generation,
                    key=command.key,
                    digest=digest,
                    response=saved.model_dump_json(by_alias=True),
                ),
            )
            return saved

    @staticmethod
    def _row(connection: Connection, owner: UUID, generation: int) -> RowMapping | None:
        return (
            connection.execute(
                text(
                    "SELECT * FROM library_preferences "
                    "WHERE owner_id=:owner AND generation=:generation"
                ),
                dict(owner=owner, generation=generation),
            )
            .mappings()
            .first()
        )

    @staticmethod
    def _view(row: RowMapping) -> LongTermPreferencesViewV1:
        return LongTermPreferencesViewV1(
            revision=row["revision"],
            preferences=row["preferences"],
            updated_at=row["updated_at"],
        )
