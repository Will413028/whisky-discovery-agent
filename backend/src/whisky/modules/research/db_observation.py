"""Observe product snapshots through a persisted, owned AG-UI turn."""

import asyncio
from uuid import UUID

from whisky.modules.research.observation import ObserveInput
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.store import ResearchStore
from whisky.modules.research.views import ReportView, TaskView


class DBObservationSource:
    def __init__(
        self, store: ResearchStore, reports: ReportStore | None = None
    ) -> None:
        self.store = store
        self.reports = reports

    async def read(self, request: ObserveInput, owner: UUID) -> TaskView | None:
        return await asyncio.to_thread(
            self.store.observed_task, request.task_id, request.run_id, owner
        )

    async def outcome(self, request: ObserveInput, owner: UUID) -> dict | None:
        return await asyncio.to_thread(
            self.store.turn_outcome, request.task_id, request.run_id, owner
        )

    async def report(self, report_id: UUID, owner: UUID) -> ReportView | None:
        if self.reports is None:
            return None
        return await asyncio.to_thread(self.reports.read, owner, report_id)
