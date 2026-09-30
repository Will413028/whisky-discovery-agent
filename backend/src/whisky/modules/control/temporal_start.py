"""Temporal starter for deterministic control workflow identities."""

import asyncio

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from whisky.modules.control.store import ControlReceipt
from whisky.modules.control.workflow import ControlWorkflow


class ConnectingTemporalControlStarter:
    """Share one lazy API client while Temporal remains independently restartable."""

    def __init__(self, address: str, namespace: str, task_queue: str) -> None:
        self.address = address
        self.namespace = namespace
        self.task_queue = task_queue
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def start(self, receipt: ControlReceipt) -> str | None:
        async with self._lock:
            if self._client is None:
                self._client = await Client.connect(
                    self.address, namespace=self.namespace, lazy=True
                )
            client = self._client
        return await TemporalControlStarter(client, self.task_queue).start(receipt)


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
