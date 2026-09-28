import asyncio
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from temporalio import workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


@workflow.defn
class TimerProbe:
    @workflow.run
    async def run(self) -> str:
        await workflow.sleep(timedelta(days=7))
        return "elapsed"


@pytest.mark.integration
async def test_time_skipping_executes_seven_day_timer():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = f"whisky-timer-{uuid4()}"
        async with Worker(env.client, task_queue=queue, workflows=[TimerProbe]):
            assert env.supports_time_skipping
            before = await env.get_current_time()
            result = await asyncio.wait_for(
                env.client.execute_workflow(
                    TimerProbe.run,
                    id=f"whisky-timer-{uuid4()}",
                    task_queue=queue,
                ),
                timeout=20,
            )
            assert result == "elapsed"
            assert await env.get_current_time() - before >= timedelta(days=7)


@pytest.mark.integration
async def test_worker_process_executes_bootstrap_probe(tmp_path):
    async with await WorkflowEnvironment.start_local() as env:
        queue = f"whisky-probe-{uuid4()}"
        process = await asyncio.create_subprocess_exec(
            str(Path(sys.executable).parent / "whisky-worker"),
            "--address",
            env.client.service_client.config.target_host,
            "--task-queue",
            queue,
            "--probe-only",
            cwd=tmp_path,
        )
        try:
            handle = await env.client.start_workflow(
                "BootstrapProbe",
                id=f"whisky-probe-{uuid4()}",
                task_queue=queue,
                execution_timeout=timedelta(seconds=15),
            )
            tasks = [
                asyncio.create_task(handle.result()),
                asyncio.create_task(process.wait()),
            ]
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
                timeout=20,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            assert process.returncode is None, (
                "worker exited before processing a workflow"
            )
            assert done, "worker did not process the bootstrap probe within 20 seconds"
            assert await handle.result() == "ok"
        finally:
            if process.returncode is None:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=10)
