"""Temporal acceptance adapter; inputs come from a persisted research task."""

import asyncio
from uuid import UUID

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from whisky.modules.research.contracts import AnswerReceipt, AnswerResult
from whisky.modules.research.domain import workflow_id_for


class ConnectingTemporalResearchStarter:
    """Share a lazy client without making API startup depend on Temporal."""

    def __init__(self, address: str, namespace: str, task_queue: str) -> None:
        self.address = address
        self.namespace = namespace
        self.task_queue = task_queue
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def start(self, task_id: UUID) -> str:
        client = await self._get_client()
        return await TemporalResearchStarter(
            client, self.task_queue, workflow_type="ResearchWorkflowV3"
        ).start(task_id)

    async def answer(self, receipt: AnswerReceipt) -> AnswerResult:
        client = await self._get_client()
        return await TemporalResearchStarter(client, self.task_queue).answer(receipt)

    async def _get_client(self) -> Client:
        async with self._lock:
            if self._client is None:
                self._client = await Client.connect(
                    self.address, namespace=self.namespace, lazy=True
                )
            return self._client


class TemporalResearchStarter:
    def __init__(
        self, client: Client, task_queue: str, workflow_type: str = "ResearchWorkflow"
    ) -> None:
        self.client = client
        self.task_queue = task_queue
        self.workflow_type = workflow_type

    async def start(self, task_id: UUID) -> str:
        workflow_id = workflow_id_for(task_id)
        try:
            handle = await self.client.start_workflow(
                self.workflow_type,
                str(task_id),
                id=workflow_id,
                task_queue=self.task_queue,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError as error:
            # A retained closed execution is accepted work, not a new attempt.
            existing = self.client.get_workflow_handle(workflow_id, run_id=error.run_id)
            return (await existing.describe()).run_id
        assert handle.result_run_id is not None
        return handle.result_run_id

    async def answer(self, receipt: AnswerReceipt) -> AnswerResult:
        handle = self.client.get_workflow_handle(workflow_id_for(receipt.task_id))
        return await handle.execute_update(
            "answer",
            receipt,
            id=str(receipt.id),
            result_type=AnswerResult,
        )
