"""Export V1 is independent of database rows and ordinary UI views."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue

from whisky.modules.catalog.public import (
    CatalogEvidenceExportV1,
    CatalogItemExportV1,
    CatalogPriceExportV1,
)
from whisky.modules.control.public import ConditionChangeExportV1
from whisky.modules.discovery.public import PlanExportV1
from whisky.modules.identity.public import IdentityExportV1
from whisky.modules.library.contracts import (
    BottleFeedbackViewV1,
    ConclusionViewV1,
    LibraryModel,
    LongTermPreferencesViewV1,
    LongTermPreferenceV1,
)
from whisky.modules.research.public import (
    AgentTurnExportV1,
    ComparisonExportV1,
    ProposalExportV1,
    QuestionExportV1,
    ReportCandidateExportV1,
    ReportCitationExportV1,
    ReportClaimExportV1,
    ReportExportV1,
    ReportPriceExportV1,
    ReportSourceObservationExportV1,
    ResearchInputExportV1,
    SourceObservationExportV1,
    TaskExportV1,
)
from whisky.platform.export_contracts import ExportRecord


class ConclusionExportV1(ExportRecord):
    id: UUID
    plan_id: UUID
    task_id: UUID
    report_id: UUID
    conditions_revision: int
    conditions: dict[str, JsonValue]
    catalog_release_id: UUID | None
    evaluated_on: date
    revision: int
    content: dict[str, JsonValue]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class FeedbackExportV1(ExportRecord):
    id: UUID
    bottle_version_id: UUID
    revision: int
    want_to_explore: bool
    tasting: Literal["not_tasted", "liked", "disliked"]
    tasting_reason: str
    created_at: datetime
    updated_at: datetime


class PreferencesExportV1(ExportRecord):
    revision: int
    preferences: tuple[LongTermPreferenceV1, ...]
    updated_at: datetime


class LibraryHistoryExportV1(ExportRecord):
    id: UUID
    scope: Literal["conclusions.save", "feedback.save", "preferences.save"]
    target_id: UUID
    response: ConclusionViewV1 | BottleFeedbackViewV1 | LongTermPreferencesViewV1
    created_at: datetime


class AccountExportDataV1(LibraryModel):
    identities: tuple[IdentityExportV1, ...]
    plans: tuple[PlanExportV1, ...]
    tasks: tuple[TaskExportV1, ...]
    reports: tuple[ReportExportV1, ...]
    questions: tuple[QuestionExportV1, ...]
    preference_proposals: tuple[ProposalExportV1, ...]
    source_observations: tuple[SourceObservationExportV1, ...]
    research_inputs: tuple[ResearchInputExportV1, ...]
    agent_turns: tuple[AgentTurnExportV1, ...]
    comparisons: tuple[ComparisonExportV1, ...]
    conclusions: tuple[ConclusionExportV1, ...]
    feedback: tuple[FeedbackExportV1, ...]
    preferences: tuple[PreferencesExportV1, ...]
    report_candidates: tuple[ReportCandidateExportV1, ...]
    report_claims: tuple[ReportClaimExportV1, ...]
    report_citations: tuple[ReportCitationExportV1, ...]
    report_prices: tuple[ReportPriceExportV1, ...]
    report_source_observations: tuple[ReportSourceObservationExportV1, ...]
    catalog_items: tuple[CatalogItemExportV1, ...]
    catalog_evidence: tuple[CatalogEvidenceExportV1, ...]
    catalog_prices: tuple[CatalogPriceExportV1, ...]
    library_history: tuple[LibraryHistoryExportV1, ...]
    condition_changes: tuple[ConditionChangeExportV1, ...]


class AccountExportViewV1(LibraryModel):
    schema_version: Literal[1] = 1
    owner_id: UUID
    generation: int = Field(ge=1)
    exported_at: AwareDatetime
    data: AccountExportDataV1
