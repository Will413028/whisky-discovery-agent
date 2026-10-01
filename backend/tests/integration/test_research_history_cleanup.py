import asyncio
from uuid import uuid4

import pytest
from temporalio import workflow
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from whisky.modules.research.history_cleanup import TemporalResearchHistoryPurger

pytestmark = pytest.mark.integration


@workflow.defn
class PrivateHistoryProbe:
    @workflow.run
    async def run(self, original: str) -> str:
        return original


async def test_history_cleanup_erases_every_run_without_erasing_other_workflows():
    async with await WorkflowEnvironment.start_local() as env:
        queue = f"whisky-purge-{uuid4()}"
        identifier = f"whisky-research-{uuid4()}"
        foreign = f"whisky-research-{uuid4()}"
        async with Worker(
            env.client, task_queue=queue, workflows=[PrivateHistoryProbe]
        ):
            runs = []
            for _ in range(2):
                handle = await env.client.start_workflow(
                    PrivateHistoryProbe.run,
                    "synthetic private original",
                    id=identifier,
                    task_queue=queue,
                )
                assert await handle.result() == "synthetic private original"
                runs.append(handle.result_run_id)
            other = await env.client.start_workflow(
                PrivateHistoryProbe.run,
                "other account fixture",
                id=foreign,
                task_queue=queue,
            )
            assert await other.result() == "other account fixture"
            purger = TemporalResearchHistoryPurger(env.client, page_size=1)
            async with asyncio.timeout(60):
                while not await purger.purge(identifier):
                    await asyncio.sleep(0.1)
            for run_id in runs:
                with pytest.raises(RPCError) as error:
                    await env.client.get_workflow_handle(
                        identifier, run_id=run_id
                    ).fetch_history()
                assert error.value.status == RPCStatusCode.NOT_FOUND
            assert (await other.fetch_history()).events


async def test_running_history_is_removed_and_missing_execution_is_idempotent():
    async with await WorkflowEnvironment.start_local() as env:
        identifier = f"whisky-research-{uuid4()}"
        handle = await env.client.start_workflow(
            "PrivateHistoryProbe",
            "synthetic pending private original",
            id=identifier,
            task_queue=f"no-worker-{uuid4()}",
        )
        assert (await handle.fetch_history()).events
        purger = TemporalResearchHistoryPurger(env.client)
        async with asyncio.timeout(60):
            while not await purger.purge(identifier):
                await asyncio.sleep(0.1)
        assert await purger.purge(identifier)
        with pytest.raises(RPCError) as error:
            await handle.describe()
        assert error.value.status == RPCStatusCode.NOT_FOUND


@pytest.mark.parametrize(
    "identifier", ["whisky-control-example", "whisky-research-' OR 1=1"]
)
async def test_cleanup_rejects_noncanonical_research_scope(identifier):
    async with await WorkflowEnvironment.start_local() as env:
        with pytest.raises(ValueError):
            await TemporalResearchHistoryPurger(env.client).purge(identifier)
