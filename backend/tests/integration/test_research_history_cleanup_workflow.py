import asyncio
from uuid import uuid4

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.models.function import FunctionModel
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from test_comparison_reports_v4 import comparison_commit as comparison_commit
from test_library_conclusions import completed_choice as completed_choice
from test_library_purge import delete

from whisky.bootstrap.worker import research_worker
from whisky.modules.research.domain import workflow_id_for
from whisky.modules.research.history_cleanup import TemporalResearchHistoryPurger
from whisky.modules.research.history_cleanup_activities import HistoryCleanupActivities
from whisky.modules.research.history_cleanup_workflow import (
    ResearchHistoryCleanupWorkflow,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("bootstrap", [False, True])
async def test_durable_cleanup_discovers_deleted_task_and_erases_history(
    completed_choice,
    bootstrap,
):
    engine, actor, report, choice = completed_choice
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        handle = await env.client.start_workflow(
            "ResearchWorkflowV4",
            str(report.task_id),
            id=workflow_id_for(report.task_id),
            task_queue=f"unexecuted-research-{uuid4()}",
        )
        assert (await handle.fetch_history()).events
        delete(engine, actor, choice, "plan.delete")
        activities = HistoryCleanupActivities(
            engine, TemporalResearchHistoryPurger(env.client)
        )
        queue = f"whisky-history-cleanup-{uuid4()}"
        worker = (
            research_worker(client, queue, engine, FunctionModel(lambda *_: None))
            if bootstrap
            else Worker(
                client,
                task_queue=queue,
                workflows=[ResearchHistoryCleanupWorkflow],
                activities=[activities.page, activities.erase],
            )
        )
        async with worker:
            async with asyncio.timeout(90):
                while True:
                    await env.client.execute_workflow(
                        ResearchHistoryCleanupWorkflow.run,
                        None,
                        id=f"whisky-cleanup-{uuid4()}",
                        task_queue=queue,
                    )
                    try:
                        await handle.fetch_history()
                    except RPCError as error:
                        assert error.status == RPCStatusCode.NOT_FOUND
                        break
                    await asyncio.sleep(1)
        with pytest.raises(RPCError) as error:
            await handle.fetch_history()
        assert error.value.status == RPCStatusCode.NOT_FOUND
