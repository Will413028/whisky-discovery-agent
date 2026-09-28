"""Observe product snapshots through a persisted, owned AG-UI turn."""

import asyncio
from uuid import UUID

from whisky.modules.research.observation import ObserveInput
from whisky.modules.research.store import ResearchStore
from whisky.modules.research.views import TaskView


class DBObservationSource:
    def __init__(self, store: ResearchStore) -> None:
        self.store = store

    async def read(self, request: ObserveInput, owner: UUID) -> TaskView | None:
        return await asyncio.to_thread(
            self.store.observed_task, request.task_id, request.run_id, owner
        )
