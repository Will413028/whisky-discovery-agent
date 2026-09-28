"""Explicit T02 synthetic source; run only with the probe Compose override."""

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import uvicorn
from whisky.bootstrap.api import configured_app
from whisky.bootstrap.settings import Settings
from whisky.modules.research.observation import ObserveInput
from whisky.modules.research.views import TaskView

TASK = UUID("00000000-0000-4000-8000-000000000001")
THREAD = UUID("00000000-0000-4000-8000-000000000002")
RUN = UUID("00000000-0000-4000-8000-000000000004")


class SyntheticSource:
    def __init__(self, owner: UUID, clock: Callable[[], float] = time.monotonic):
        self.owner = owner
        self.clock = clock
        self.started: float | None = None

    async def read(self, request: ObserveInput, owner: UUID) -> TaskView | None:
        if (
            owner != self.owner
            or request.task_id != TASK
            or request.run_id != RUN
            or request.conditions_revision != 1
        ):
            return None
        now = self.clock()
        if self.started is None:
            self.started = now
        version = 1 if now - self.started < 2 else 2
        return TaskView(
            task_id=TASK,
            thread_id=THREAD,
            conditions_revision=1,
            view_version=version,
            status="researching",
            stage=f"T02 合成串流測試，第 {version} 段；非產品研究資料",
            question=None,
            report_id=None,
            error=None,
            observed_at=datetime.now(UTC),
        )


if __name__ == "__main__":
    source = SyntheticSource(UUID(os.environ["WHISKY_PROBE_OWNER"]))
    settings = Settings.from_environment(os.environ)
    if settings is None:
        raise RuntimeError("The probe requires real identity configuration")
    uvicorn.run(configured_app(settings, source), host="0.0.0.0", port=8417)
