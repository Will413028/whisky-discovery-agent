"""Install the project's native Temporal cleanup Schedule."""

from datetime import timedelta

from temporalio.api.common.v1 import Payload
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from whisky.modules.research.history_cleanup import assert_namespace_without_archival
from whisky.modules.research.history_cleanup_workflow import (
    ResearchHistoryCleanupWorkflow,
)

SCHEDULE_ID = "whisky-research-history-cleanup-v1"


async def ensure_history_cleanup_schedule(client: Client, task_queue: str) -> None:
    await assert_namespace_without_archival(client)
    try:
        await client.create_schedule(
            SCHEDULE_ID,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    ResearchHistoryCleanupWorkflow.run,
                    None,
                    id="whisky-research-history-sweep-v1",
                    task_queue=task_queue,
                ),
                spec=ScheduleSpec(
                    intervals=[ScheduleIntervalSpec(every=timedelta(minutes=1))]
                ),
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            ),
            trigger_immediately=True,
            rpc_timeout=timedelta(seconds=10),
        )
    except ScheduleAlreadyRunningError:
        pass
    observed = (
        await client.get_schedule_handle(SCHEDULE_ID).describe(
            rpc_timeout=timedelta(seconds=10)
        )
    ).schedule
    action = observed.action
    if not isinstance(action, ScheduleActionStartWorkflow):
        raise ValueError("History cleanup Schedule has an unexpected action")
    if any(not isinstance(value, Payload) for value in action.args):
        raise ValueError("History cleanup Schedule arguments are not encoded payloads")
    args = await client.data_converter.decode(action.args)
    intervals = observed.spec.intervals
    if (
        action.workflow != "ResearchHistoryCleanupWorkflowV1"
        or action.task_queue != task_queue
        or args != [None]
        or len(intervals) != 1
        or intervals[0].every != timedelta(minutes=1)
        or intervals[0].offset not in (None, timedelta(0))
        or observed.spec.calendars
        or observed.spec.cron_expressions
        or observed.spec.skip
        or observed.spec.start_at is not None
        or observed.spec.end_at is not None
        or observed.policy.overlap != ScheduleOverlapPolicy.SKIP
        or observed.state.paused
        or observed.state.limited_actions
    ):
        raise ValueError("History cleanup Schedule differs from required configuration")
