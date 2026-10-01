"""Durable orchestration of deletion-fenced research history erasure."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from whisky.modules.research.history_cleanup_contracts import HistoryCleanupPage


@workflow.defn(name="ResearchHistoryCleanupWorkflowV1")
class ResearchHistoryCleanupWorkflow:
    @workflow.run
    async def run(self, cursor: str | None = None) -> None:
        calls = 0
        retry = RetryPolicy(maximum_interval=timedelta(minutes=5))
        while True:
            page = await workflow.execute_activity(
                "whisky_deleted_history_page_v1",
                cursor,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
                result_type=HistoryCleanupPage,
            )
            for identifier in page.workflow_ids:
                try:
                    outcome = await workflow.execute_activity(
                        "whisky_erase_research_history_v1",
                        identifier,
                        start_to_close_timeout=timedelta(minutes=1),
                        schedule_to_close_timeout=timedelta(seconds=90),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                        result_type=str,
                    )
                    if outcome == "pending":
                        workflow.logger.warning(
                            "Research history erasure pending: %s", identifier
                        )
                    elif outcome not in {"absent", "not_eligible"}:
                        raise ValueError("Unknown history erasure outcome")
                except ActivityError:
                    workflow.logger.error(
                        "Research history erasure failed; retry next sweep: %s",
                        identifier,
                    )
                calls += 1
                if calls >= 1000:
                    workflow.continue_as_new(cursor)
            if page.cursor is None:
                return
            cursor = page.cursor
            calls += 1
            if calls >= 1000:
                workflow.continue_as_new(cursor)
