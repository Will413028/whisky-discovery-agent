import asyncio
from uuid import uuid4

import pytest
from temporalio import workflow
from temporalio.client import Client, Interceptor, OutboundInterceptor
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from whisky.modules.research.temporal_start import TemporalResearchStarter


@workflow.defn(name="ResearchWorkflow")
class CompletedResearchFixture:
    """Only tests start acceptance; does not perform or validate research."""

    @workflow.run
    async def run(self, task_id: str) -> str:
        return task_id


@pytest.mark.integration
async def test_completed_execution_is_not_run_again_on_retry():
    async with await WorkflowEnvironment.start_local() as env:
        queue = f"whisky-test-{uuid4()}"
        async with Worker(
            env.client, task_queue=queue, workflows=[CompletedResearchFixture]
        ):
            starter = TemporalResearchStarter(env.client, queue)
            task_id = uuid4()
            original = await starter.start(task_id)
            handle = env.client.get_workflow_handle(f"whisky-research-{task_id}")
            assert await asyncio.wait_for(handle.result(), timeout=10) == str(task_id)
            assert await starter.start(task_id) == original
            assert (await handle.describe()).run_id == original


@pytest.mark.integration
async def test_concurrent_starts_return_same_accepted_execution():
    async with await WorkflowEnvironment.start_local() as env:
        starter = TemporalResearchStarter(env.client, f"whisky-test-{uuid4()}")
        task_id = uuid4()
        runs = await asyncio.gather(starter.start(task_id), starter.start(task_id))
        assert runs[0] == runs[1]
        description = await env.client.get_workflow_handle(
            f"whisky-research-{task_id}"
        ).describe()
        assert description.run_id == runs[0]


@pytest.mark.integration
async def test_closed_execution_is_found_without_starting_a_replacement():
    async with await WorkflowEnvironment.start_local() as env:
        starter = TemporalResearchStarter(env.client, f"whisky-test-{uuid4()}")
        task_id = uuid4()
        original = await starter.start(task_id)
        handle = env.client.get_workflow_handle(f"whisky-research-{task_id}")
        await handle.terminate("isolated test closes accepted execution")
        assert await starter.start(task_id) == original
        assert (await handle.describe()).run_id == original


class LoseFirstResponse(Interceptor):
    def intercept_client(self, next):
        class Lose(OutboundInterceptor):
            lost = False

            async def start_workflow(self, input):
                handle = await super().start_workflow(input)
                if not self.lost:
                    self.lost = True
                    raise TimeoutError("injected after real server acceptance")
                return handle

        return Lose(next)


@pytest.mark.integration
async def test_lost_start_response_retry_finds_original_execution():
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(
            **{**env.client.config(), "interceptors": [LoseFirstResponse()]}
        )
        starter = TemporalResearchStarter(client, f"whisky-test-{uuid4()}")
        task_id = uuid4()
        with pytest.raises(TimeoutError, match="after real server acceptance"):
            await starter.start(task_id)
        original = await env.client.get_workflow_handle(
            f"whisky-research-{task_id}"
        ).describe()
        assert await starter.start(task_id) == original.run_id
