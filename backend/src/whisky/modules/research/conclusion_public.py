"""Research-owned immutable source for a user exploration conclusion."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import Connection, text

from whisky.modules.catalog.public import published_item_name
from whisky.modules.discovery.public import ResearchConditionsV1


@dataclass(frozen=True)
class ConcludableCandidate:
    version_id: UUID
    name: str


@dataclass(frozen=True)
class ConcludableReport:
    id: UUID
    plan_id: UUID
    task_id: UUID
    conditions_revision: int
    conditions: ResearchConditionsV1
    catalog_release_id: UUID | None
    evaluated_on: date
    candidates: tuple[ConcludableCandidate, ...]

    @property
    def candidate_version_ids(self) -> tuple[UUID, ...]:
        return tuple(candidate.version_id for candidate in self.candidates)


def concludable_report(
    connection: Connection,
    owner: UUID,
    generation: int,
    plan_id: UUID | None,
    report_id: UUID,
) -> ConcludableReport | None:
    plan_filter = "AND t.plan_id=:plan" if plan_id is not None else ""
    row = connection.execute(
        text(f"""
        SELECT r.id,r.task_id,r.conditions_revision,r.catalog_release_id,
            r.evaluated_on,t.conditions,t.plan_id
        FROM research_reports r JOIN research_tasks t
            ON t.id=r.task_id AND t.owner_id=r.owner_id AND t.generation=r.generation
        WHERE r.id=:report AND r.owner_id=:owner AND r.generation=:generation
            {plan_filter} AND t.status='completed' AND t.report_id=r.id
    """),
        dict(report=report_id, owner=owner, generation=generation, plan=plan_id),
    ).first()
    if row is None:
        return None
    candidates = []
    for candidate in connection.execute(
        text(
            "SELECT bottle_version_id,release_id,item_id "
            "FROM research_report_candidates "
            "WHERE report_id=:report ORDER BY ordinal"
        ),
        {"report": report_id},
    ):
        name = published_item_name(
            connection,
            candidate.release_id,
            candidate.item_id,
            candidate.bottle_version_id,
        )
        if name is None:
            raise RuntimeError("Saved report has an unresolved bottle")
        candidates.append(ConcludableCandidate(candidate.bottle_version_id, name))
    return ConcludableReport(
        row.id,
        row.plan_id,
        row.task_id,
        row.conditions_revision,
        ResearchConditionsV1.model_validate(row.conditions),
        row.catalog_release_id,
        row.evaluated_on,
        tuple(candidates),
    )
