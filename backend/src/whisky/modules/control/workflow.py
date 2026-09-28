"""Deterministic command ordering; all external and DB I/O lives in activities."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=5),
)


@workflow.defn(name="ControlWorkflowV1")
class ControlWorkflow:
    @workflow.run
    async def run(self, command_id: str) -> str:
        await workflow.execute_activity(
            "whisky_control_intent_v1",
            command_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_RETRY,
            result_type=str,
        )
        await workflow.execute_activity(
            "whisky_control_effect_v1",
            command_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_RETRY,
            result_type=str,
        )
        status = await workflow.execute_activity(
            "whisky_control_result_v1",
            command_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_RETRY,
            result_type=str,
        )
        try:
            await workflow.execute_activity(
                "whisky_control_notify_v1",
                command_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except ActivityError:
            # The DB fence remains authoritative if cooperative cancellation fails.
            pass
        return status
