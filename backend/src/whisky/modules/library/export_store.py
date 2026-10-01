"""Bounded complete JSON export from one owner-scoped database snapshot."""

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from time import monotonic
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, event, text

from whisky.modules.catalog.public import export_references
from whisky.modules.control.public import export_condition_changes
from whisky.modules.discovery.public import export_plans, visible_plan_export_scope
from whisky.modules.identity.public import actor_generation, export_identities
from whisky.modules.library.export_file import ExportFileWriter, PreparedAccountExport
from whisky.modules.research.public import (
    export_research,
    research_catalog_export_scopes,
)

MAX_EXPORT_BYTES = 8 * 1024 * 1024
MAX_EXPORT_SECONDS = 110


class ExportUnavailable(ValueError):
    pass


@contextmanager
def export_deadline(
    connection: Connection, started: float
) -> Iterator[Callable[[], float]]:
    def remaining() -> float:
        seconds = MAX_EXPORT_SECONDS - (monotonic() - started)
        if seconds <= 0:
            raise ExportUnavailable("EXPORT_TIMEOUT")
        return seconds

    def before_query(
        connection: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        milliseconds = max(1, min(5000, int(remaining() * 1000)))
        driver = connection.connection.driver_connection
        if driver is None:
            raise ExportUnavailable("EXPORT_UNAVAILABLE")
        with driver.cursor() as timeout_cursor:
            timeout_cursor.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(milliseconds),),
            )

    remaining()
    event.listen(connection, "before_cursor_execute", before_query)
    try:
        yield remaining
        remaining()
    finally:
        event.remove(connection, "before_cursor_execute", before_query)


class AccountExportStore:
    def __init__(self, engine: Engine, max_bytes: int = MAX_EXPORT_BYTES) -> None:
        self.engine = engine
        self.max_bytes = max_bytes

    def read(self, owner: UUID, generation: int) -> bytes:
        prepared = self.prepare(owner, generation, max_bytes=self.max_bytes)
        try:
            return prepared.file.read()
        finally:
            prepared.file.close()

    def prepare(
        self, owner: UUID, generation: int, *, max_bytes: int | None = None
    ) -> PreparedAccountExport:
        started = monotonic()

        def check_deadline() -> None:
            if monotonic() - started >= MAX_EXPORT_SECONDS:
                raise ExportUnavailable("EXPORT_TIMEOUT")

        writer = ExportFileWriter(
            owner, generation, directory=os.environ.get("WHISKY_EXPORT_DIRECTORY")
        )
        try:
            check_deadline()
            self._write(owner, generation, writer, max_bytes, started)
            check_deadline()
            prepared = writer.finish()
            check_deadline()
            if max_bytes is not None and prepared.size > max_bytes:
                raise ExportUnavailable("EXPORT_TOO_LARGE")
            return prepared
        except BaseException:
            writer.file.close()
            raise

    def _write(
        self,
        owner: UUID,
        generation: int,
        writer: ExportFileWriter,
        max_bytes: int | None,
        started: float,
    ) -> None:
        with (
            self.engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection,
            connection.begin(),
            export_deadline(connection, started) as remaining,
        ):
            if actor_generation(connection, owner, lock=True) != generation:
                raise ExportUnavailable("IDENTITY_CHANGED")

            def append(section: str, value: dict) -> None:
                remaining()
                writer.append(section, value)
                if max_bytes is not None and writer.file.tell() > max_bytes:
                    raise ExportUnavailable("EXPORT_TOO_LARGE")

            for identity in export_identities(connection, owner):
                append("identities", identity.model_dump(mode="json"))
            for row in export_plans(connection, owner, generation):
                append("plans", row)
            scope = visible_plan_export_scope(owner, generation)
            for row in export_condition_changes(connection, scope):
                append("conditionChanges", row)
            for section, row in export_research(connection, scope):
                append(section, row)
            for section, row in export_references(
                connection, research_catalog_export_scopes(scope)
            ):
                append(section, row)
            queries = (
                (
                    "libraryHistory",
                    """
                    SELECT id,scope,target_id,response,created_at
                    FROM library_commands
                    WHERE owner_id=:owner AND generation=:generation AND (
                        scope IN ('feedback.save','preferences.save') OR
                        (scope='conclusions.save' AND target_id IN (
                            SELECT id FROM library_conclusions
                            WHERE owner_id=:owner AND generation=:generation
                                AND deleted_at IS NULL AND plan_id IN (__PLAN_SCOPE__)
                        ))
                    ) ORDER BY created_at,id
                    """,
                ),
                (
                    "conclusions",
                    """
                    SELECT id,plan_id,task_id,report_id,conditions_revision,
                        conditions,catalog_release_id,evaluated_on,revision,
                        content,created_at,updated_at,deleted_at
                    FROM library_conclusions
                    WHERE owner_id=:owner AND generation=:generation
                        AND deleted_at IS NULL AND plan_id IN (__PLAN_SCOPE__)
                    ORDER BY id
                """,
                ),
                (
                    "feedback",
                    """
                    SELECT id,bottle_version_id,revision,want_to_explore,tasting,
                        tasting_reason,created_at,updated_at
                    FROM library_bottle_feedback
                    WHERE owner_id=:owner AND generation=:generation ORDER BY id
                """,
                ),
                (
                    "preferences",
                    """
                    SELECT revision,preferences,updated_at FROM library_preferences
                    WHERE owner_id=:owner AND generation=:generation
                """,
                ),
            )
            for section, query in queries:
                for row in (
                    connection.execution_options(stream_results=True)
                    .execute(
                        text(
                            "SELECT to_jsonb(export_row) FROM ("
                            + query.replace("__PLAN_SCOPE__", scope.sql)
                            + ") export_row"
                        ),
                        scope.parameters,
                    )
                    .scalars()
                ):
                    append(section, row)
