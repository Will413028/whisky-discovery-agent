from datetime import timedelta
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from whisky.modules.research.history_cleanup_contracts import HistoryCleanupPage
from whisky.modules.research.history_cleanup_workflow import (
    ResearchHistoryCleanupWorkflow,
)

pytestmark = pytest.mark.integration


class PendingFirstProbe:
    def __init__(self, outcome):
        self.visited = []
        self.outcome = outcome

    @activity.defn(name="whisky_deleted_history_page_v1")
    async def page(self, cursor: str | None) -> HistoryCleanupPage:
        return HistoryCleanupPage(("first-fixture", "second-fixture"), None)

    @activity.defn(name="whisky_erase_research_history_v1")
    async def erase(self, identifier: str) -> str:
        self.visited.append(identifier)
        if identifier == "first-fixture" and self.outcome == "failure":
            raise RuntimeError("synthetic per-execution provider failure")
        return "pending" if identifier == "first-fixture" else "absent"


@pytest.mark.parametrize("outcome", ["pending", "failure"])
async def test_pending_execution_does_not_starve_other_deleted_tasks(outcome):
    probe = PendingFirstProbe(outcome)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = f"cleanup-progress-{uuid4()}"
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[ResearchHistoryCleanupWorkflow],
            activities=[probe.page, probe.erase],
        ):
            await env.client.execute_workflow(
                ResearchHistoryCleanupWorkflow.run,
                None,
                id=f"cleanup-progress-{uuid4()}",
                task_queue=queue,
                execution_timeout=timedelta(seconds=10),
            )
    assert probe.visited == (
        ["first-fixture", "second-fixture"]
        if outcome == "pending"
        else ["first-fixture", "first-fixture", "second-fixture"]
    )
