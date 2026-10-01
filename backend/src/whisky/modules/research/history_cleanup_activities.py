"""All database and native Temporal cleanup I/O happens in activities."""

import asyncio
from typing import Literal

from sqlalchemy import Engine
from temporalio import activity

from whisky.modules.research.history_cleanup import TemporalResearchHistoryPurger
from whisky.modules.research.history_cleanup_contracts import HistoryCleanupPage
from whisky.modules.research.history_cleanup_store import (
    deleted_history_page,
    history_erasure_allowed,
)


class HistoryCleanupActivities:
    def __init__(self, engine: Engine, purger: TemporalResearchHistoryPurger) -> None:
        self.engine = engine
        self.purger = purger

    @activity.defn(name="whisky_deleted_history_page_v1")
    async def page(self, cursor: str | None) -> HistoryCleanupPage:
        return await asyncio.to_thread(deleted_history_page, self.engine, cursor)

    @activity.defn(name="whisky_erase_research_history_v1")
    async def erase(
        self, workflow_id: str
    ) -> Literal["absent", "pending", "not_eligible"]:
        if not await asyncio.to_thread(
            history_erasure_allowed, self.engine, workflow_id
        ):
            return "not_eligible"
        return "absent" if await self.purger.purge(workflow_id) else "pending"
