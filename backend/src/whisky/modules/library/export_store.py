"""Bounded complete JSON export from one owner-scoped database snapshot."""

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine, text

from whisky.modules.catalog.public import export_references
from whisky.modules.control.public import export_condition_changes
from whisky.modules.discovery.public import export_plans
from whisky.modules.identity.public import actor_generation, export_identities
from whisky.modules.library.export_views import AccountExportDataV1, AccountExportViewV1
from whisky.modules.research.public import export_research

MAX_EXPORT_BYTES = 8 * 1024 * 1024


class ExportUnavailable(ValueError):
    pass


class AccountExportStore:
    def __init__(self, engine: Engine, max_bytes: int = MAX_EXPORT_BYTES) -> None:
        self.engine = engine
        self.max_bytes = max_bytes

    def read(self, owner: UUID, generation: int) -> bytes:
        with (
            self.engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection,
            connection.begin(),
        ):
            connection.execute(text("SET LOCAL statement_timeout='5s'"))
            if actor_generation(connection, owner, lock=True) != generation:
                raise ExportUnavailable("IDENTITY_CHANGED")
            data: dict[str, list] = {
                name: []
                for name in (
                    "identities",
                    "libraryHistory",
                    "conditionChanges",
                    "plans",
                    "tasks",
                    "reports",
                    "questions",
                    "preferenceProposals",
                    "sourceObservations",
                    "researchInputs",
                    "agentTurns",
                    "comparisons",
                    "conclusions",
                    "feedback",
                    "preferences",
                    "reportCandidates",
                    "reportClaims",
                    "reportCitations",
                    "reportPrices",
                    "reportSourceObservations",
                    "catalogItems",
                    "catalogEvidence",
                    "catalogPrices",
                )
            }
            size = 0

            def append(section: str, value: dict) -> None:
                nonlocal size
                size += len(json.dumps(value, ensure_ascii=False).encode())
                if size > self.max_bytes:
                    raise ExportUnavailable("EXPORT_TOO_LARGE")
                data[section].append(value)

            for identity in export_identities(connection, owner):
                append("identities", identity.model_dump(mode="json"))
            for row in export_plans(connection, owner, generation):
                append("plans", row)
            plan_ids = tuple(UUID(row["id"]) for row in data["plans"])
            for row in export_condition_changes(
                connection, owner, generation, plan_ids
            ):
                append("conditionChanges", row)
            for section, row in export_research(
                connection, owner, generation, plan_ids
            ):
                append(section, row)
            for section, row in export_references(
                connection,
                items={
                    (str(row["release_id"]), str(row["item_id"]))
                    for row in data["reportCandidates"]
                },
                evidence={
                    (str(row["release_id"]), str(row["evidence_id"]))
                    for row in data["reportCitations"] + data["sourceObservations"]
                },
                prices={
                    (str(row["release_id"]), str(row["price_id"]))
                    for row in data["reportPrices"]
                },
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
                                AND deleted_at IS NULL AND plan_id=ANY(:plan_ids)
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
                        AND deleted_at IS NULL AND plan_id=ANY(:plan_ids) ORDER BY id
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
                            + query
                            + ") export_row"
                        ),
                        dict(
                            owner=owner, generation=generation, plan_ids=list(plan_ids)
                        ),
                    )
                    .scalars()
                ):
                    append(section, row)
            result = (
                AccountExportViewV1(
                    owner_id=owner,
                    generation=generation,
                    exported_at=datetime.now(UTC),
                    data=AccountExportDataV1.model_validate(data),
                )
                .model_dump_json(by_alias=True)
                .encode()
            )
            if len(result) > self.max_bytes:
                raise ExportUnavailable("EXPORT_TOO_LARGE")
            return result
