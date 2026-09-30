"""Public V4 comparison projections do not alter legacy ReportView."""

from datetime import date
from typing import Literal
from uuid import UUID

from whisky.modules.discovery.public import CatalogReference
from whisky.modules.research.comparison_v4 import ComparisonArtifactV4
from whisky.modules.research.views import ReportSourceView, ViewModel


class ComparisonItemEvidenceV4(ViewModel):
    reference: CatalogReference
    name: str
    sources: tuple[ReportSourceView, ...]


class ComparisonReportViewV4(ViewModel):
    schema_version: Literal[4] = 4
    report_id: UUID
    task_id: UUID
    conditions_revision: int
    catalog_release_id: UUID | None
    evaluated_on: date
    comparison: ComparisonArtifactV4
    items: tuple[ComparisonItemEvidenceV4, ...]
