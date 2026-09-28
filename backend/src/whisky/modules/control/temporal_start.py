"""Temporal starter for deterministic control workflow identities."""

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from whisky.modules.control.store import ControlReceipt
from whisky.modules.control.workflow import ControlWorkflow


class TemporalControlStarter:
    def __init__(self, client: Client, task_queue: str) -> None:
        self.client = client
        self.task_queue = task_queue

    async def start(self, receipt: ControlReceipt) -> str | None:
        try:
            handle = await self.client.start_workflow(
                ControlWorkflow.run,
                str(receipt.id),
                id=receipt.workflow_id,
                task_queue=self.task_queue,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError as error:
            return error.run_id
        return handle.result_run_id
