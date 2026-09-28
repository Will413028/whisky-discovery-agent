"""Typed model choice between a cited report and a human version question."""

from dataclasses import dataclass

from whisky.modules.research.report import ReportDraft


@dataclass(frozen=True)
class ClarificationDraft:
    prompt: str
    choices: tuple[str, ...]


@dataclass(frozen=True)
class ResearchDecision:
    report: ReportDraft | None = None
    clarification: ClarificationDraft | None = None

    def selected(self) -> ReportDraft | ClarificationDraft:
        if (self.report is None) == (self.clarification is None):
            raise ValueError("Research must choose one report or clarification")
        if self.report is not None:
            return self.report
        assert self.clarification is not None
        return self.clarification
