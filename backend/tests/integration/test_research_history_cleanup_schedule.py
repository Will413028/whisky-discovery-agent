import pytest
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment

from whisky.modules.research.history_cleanup_schedule import (
    SCHEDULE_ID,
    ensure_history_cleanup_schedule,
)

pytestmark = pytest.mark.integration


async def test_cleanup_schedule_is_installed_and_restart_preserves_it():
    async with await WorkflowEnvironment.start_local() as env:
        queue = "whisky-cleanup-schedule-fixture"
        await ensure_history_cleanup_schedule(env.client, queue)
        found = True
        try:
            first = await env.client.get_schedule_handle(SCHEDULE_ID).describe()
        except RPCError as error:
            assert error.status == RPCStatusCode.NOT_FOUND
            found = False
        assert found, "Worker startup must install the durable history cleanup Schedule"
        await ensure_history_cleanup_schedule(env.client, queue)
        second = await env.client.get_schedule_handle(SCHEDULE_ID).describe()
        assert first.schedule == second.schedule


@pytest.mark.parametrize("change", ["queue", "paused"])
async def test_existing_schedule_mismatch_is_not_silently_overwritten(change):
    async with await WorkflowEnvironment.start_local() as env:
        await ensure_history_cleanup_schedule(env.client, "fixture-queue")
        if change == "paused":
            await env.client.get_schedule_handle(SCHEDULE_ID).pause()
        with pytest.raises(ValueError, match="required configuration"):
            await ensure_history_cleanup_schedule(
                env.client, "other-queue" if change == "queue" else "fixture-queue"
            )
