"""V4 payloads extend execution without rewriting legacy history contracts."""

from dataclasses import dataclass
from datetime import datetime

from whisky.modules.discovery.public import PreferenceProposal
from whisky.modules.research.comparison_v4 import ComparisonArtifactV4
from whisky.modules.research.contracts import ReportCommit, ResearchRunContext
from whisky.modules.research.inputs_v4 import ResearchInputV4


@dataclass(frozen=True)
class ResearchExecutionV4:
    context: ResearchRunContext
    input: ResearchInputV4


@dataclass(frozen=True)
class PreferenceQuestionCommitV4:
    context: ResearchRunContext
    waiting_version: int
    source_text: str
    proposal: PreferenceProposal
    expires_at: datetime


@dataclass(frozen=True)
class ReportCommitV4:
    report: ReportCommit
    comparison: ComparisonArtifactV4
