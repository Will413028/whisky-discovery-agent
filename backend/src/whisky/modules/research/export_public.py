"""Private research records; explicit fields exclude runtime credentials."""

from collections.abc import Iterator
from datetime import date, datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import Connection, text
from sqlalchemy.engine import ScalarResult

from whisky.platform.export_contracts import ExportRecord


class TaskExportV1(ExportRecord):
    id: UUID
    plan_id: UUID
    generation: int
    conditions_revision: int
    conditions: dict[str, JsonValue]
    thread_id: UUID
    status: str
    stage: str
    question: JsonValue
    report_id: UUID | None
    error: JsonValue
    created_at: datetime
    updated_at: datetime


class ReportExportV1(ExportRecord):
    id: UUID
    task_id: UUID
    generation: int
    conditions_revision: int
    catalog_release_id: UUID | None
    evaluated_on: date
    policy_version: str
    prompt_version: str
    model_version: str
    schema_version: int
    content: dict[str, JsonValue]
    clarification_id: UUID | None
    selected_version_id: UUID | None
    selected_label: str | None
    selected_item_id: UUID | None
    created_at: datetime


class QuestionExportV1(ExportRecord):
    id: UUID
    task_id: UUID
    generation: int
    conditions_revision: int
    waiting_version: int
    kind: str
    prompt: str
    choices: JsonValue
    status: str
    expires_at: datetime
    answer: str | None
    created_at: datetime
    answered_at: datetime | None


class ProposalExportV1(ExportRecord):
    task_id: UUID
    plan_id: UUID
    generation: int
    conditions_revision: int
    base_conditions: dict[str, JsonValue]
    source_text: str
    proposal: dict[str, JsonValue]
    prompt_version: str
    created_at: datetime


class SourceObservationExportV1(ExportRecord):
    id: UUID
    task_id: UUID
    generation: int
    conditions_revision: int
    release_id: UUID
    bottle_version_id: UUID
    evidence_id: UUID
    status: str
    review_status: str
    error_code: str | None
    visible_text: str | None
    effective_url: str | None
    content_sha256: str | None
    source_checked_on: date
    observed_at: datetime


class ResearchInputExportV1(ExportRecord):
    task_id: UUID
    input: dict[str, JsonValue]
    source_task_id: UUID | None


class AgentTurnExportV1(ExportRecord):
    task_id: UUID
    thread_id: UUID
    run_id: UUID
    outcome: JsonValue
    created_at: datetime


class ComparisonExportV1(ExportRecord):
    report_id: UUID
    task_id: UUID
    schema_version: int
    content: dict[str, JsonValue]


class ReportCandidateExportV1(ExportRecord):
    report_id: UUID
    ordinal: int
    release_id: UUID
    item_id: UUID
    bottle_version_id: UUID
    reason: str


class ReportClaimExportV1(ExportRecord):
    report_id: UUID
    ordinal: int
    claim_ordinal: int
    release_id: UUID
    item_id: UUID
    bottle_version_id: UUID
    kind: str
    key: str
    value: str


class ReportCitationExportV1(ExportRecord):
    report_id: UUID
    ordinal: int
    claim_ordinal: int
    release_id: UUID
    item_id: UUID
    bottle_version_id: UUID
    kind: str
    key: str
    evidence_id: UUID


class ReportPriceExportV1(ExportRecord):
    report_id: UUID
    ordinal: int
    release_id: UUID
    item_id: UUID
    bottle_version_id: UUID
    price_id: UUID


class ReportSourceObservationExportV1(ExportRecord):
    report_id: UUID
    ordinal: int
    observation_id: UUID


def export_research(
    connection: Connection, owner: UUID, generation: int, plan_ids: tuple[UUID, ...]
) -> Iterator[tuple[str, dict[str, JsonValue]]]:
    queries = (
        (
            "tasks",
            """
            SELECT id,plan_id,generation,conditions_revision,conditions,
                thread_id,status,stage,question,report_id,error,
                created_at,updated_at
            FROM research_tasks WHERE owner_id=:owner AND generation=:generation
                AND plan_id=ANY(:plan_ids)
            ORDER BY created_at,id
        """,
        ),
        (
            "reports",
            """
            SELECT id,task_id,generation,conditions_revision,catalog_release_id,
                evaluated_on,policy_version,prompt_version,model_version,
                schema_version,content,clarification_id,selected_version_id,
                selected_label,selected_item_id,created_at
            FROM research_reports WHERE owner_id=:owner AND generation=:generation
                AND task_id IN (SELECT id FROM research_tasks
                    WHERE owner_id=:owner AND generation=:generation
                        AND plan_id=ANY(:plan_ids))
            ORDER BY created_at,id
        """,
        ),
        (
            "questions",
            """
            SELECT id,task_id,generation,conditions_revision,waiting_version,
                kind,prompt,choices,status,expires_at,answer,created_at,answered_at
            FROM clarifications WHERE owner_id=:owner AND generation=:generation
                AND task_id IN (SELECT id FROM research_tasks
                    WHERE owner_id=:owner AND generation=:generation
                        AND plan_id=ANY(:plan_ids))
            ORDER BY created_at,id
        """,
        ),
        (
            "preferenceProposals",
            """
            SELECT task_id,plan_id,generation,conditions_revision,base_conditions,
                source_text,proposal,prompt_version,created_at
            FROM preference_proposals
            WHERE owner_id=:owner AND generation=:generation
                AND plan_id=ANY(:plan_ids) ORDER BY task_id
        """,
        ),
        (
            "sourceObservations",
            """
            SELECT id,task_id,generation,conditions_revision,release_id,
                bottle_version_id,evidence_id,status,review_status,error_code,
                visible_text,effective_url,content_sha256,source_checked_on,observed_at
            FROM research_source_observations
            WHERE owner_id=:owner AND generation=:generation
                AND task_id IN (SELECT id FROM research_tasks
                    WHERE owner_id=:owner AND generation=:generation
                        AND plan_id=ANY(:plan_ids)) ORDER BY observed_at,id
        """,
        ),
        (
            "researchInputs",
            """
            SELECT i.task_id,i.input,i.source_task_id FROM research_v4_inputs i
            JOIN research_tasks t ON t.id=i.task_id AND t.owner_id=i.owner_id
            WHERE t.owner_id=:owner AND t.generation=:generation
                AND t.plan_id=ANY(:plan_ids) ORDER BY i.task_id
        """,
        ),
        (
            "agentTurns",
            """
            SELECT a.task_id,a.thread_id,a.run_id,a.outcome,a.created_at
            FROM agent_turns a
            JOIN research_tasks t ON t.id=a.task_id AND t.owner_id=a.owner_id
            WHERE t.owner_id=:owner AND t.generation=:generation
                AND t.plan_id=ANY(:plan_ids)
            ORDER BY a.created_at,a.run_id
        """,
        ),
        (
            "comparisons",
            """
            SELECT c.report_id,c.task_id,c.schema_version,c.content
            FROM research_report_comparisons c
            JOIN research_reports r ON r.id=c.report_id AND r.owner_id=c.owner_id
            WHERE r.owner_id=:owner AND r.generation=:generation
                AND r.task_id IN (SELECT id FROM research_tasks
                    WHERE owner_id=:owner AND generation=:generation
                        AND plan_id=ANY(:plan_ids)) ORDER BY c.report_id
        """,
        ),
    )
    for section, query in queries:
        rows: ScalarResult[dict[str, JsonValue]] = (
            connection.execution_options(stream_results=True)
            .execute(
                text("SELECT to_jsonb(export_row) FROM (" + query + ") export_row"),
                dict(owner=owner, generation=generation, plan_ids=list(plan_ids)),
            )
            .scalars()
        )
        for row in rows:
            yield section, row
    for section, table, columns, ordering in (
        (
            "reportCandidates",
            "research_report_candidates",
            "report_id,ordinal,release_id,item_id,bottle_version_id,reason",
            "report_id,ordinal",
        ),
        (
            "reportClaims",
            "research_report_claims",
            "report_id,ordinal,claim_ordinal,release_id,item_id,bottle_version_id,kind,key,value",
            "report_id,ordinal,claim_ordinal",
        ),
        (
            "reportCitations",
            "research_report_citations",
            "report_id,ordinal,claim_ordinal,release_id,item_id,bottle_version_id,kind,key,evidence_id",
            "report_id,ordinal,claim_ordinal,evidence_id",
        ),
        (
            "reportPrices",
            "research_report_prices",
            "report_id,ordinal,release_id,item_id,bottle_version_id,price_id",
            "report_id,ordinal,price_id",
        ),
        (
            "reportSourceObservations",
            "research_report_source_observations",
            "report_id,ordinal,observation_id",
            "report_id,ordinal",
        ),
    ):
        # Table and column names are fixed module-owned definitions, never input.
        query = (
            f"SELECT to_jsonb(export_row) FROM (SELECT {columns} FROM {table} "
            "WHERE report_id IN (SELECT id FROM research_reports "
            "WHERE owner_id=:owner AND generation=:generation "
            "AND task_id IN (SELECT id FROM research_tasks "
            "WHERE owner_id=:owner AND generation=:generation "
            "AND plan_id=ANY(:plan_ids))) "
            f"ORDER BY {ordering}) export_row"
        )
        related: ScalarResult[dict[str, JsonValue]] = (
            connection.execution_options(stream_results=True)
            .execute(
                text(query),
                dict(owner=owner, generation=generation, plan_ids=list(plan_ids)),
            )
            .scalars()
        )
        for row in related:
            yield section, row
