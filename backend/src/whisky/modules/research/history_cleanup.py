"""Native Temporal history erasure adapter for deletion-fenced research tasks."""

from datetime import timedelta
from uuid import UUID

from temporalio.api.common.v1 import WorkflowExecution
from temporalio.api.enums.v1 import ArchivalState
from temporalio.api.workflowservice.v1 import (
    DeleteWorkflowExecutionRequest,
    DescribeNamespaceRequest,
)
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

_RPC_TIMEOUT = timedelta(seconds=5)


async def assert_namespace_without_archival(client: Client) -> None:
    description = await client.workflow_service.describe_namespace(
        DescribeNamespaceRequest(namespace=client.namespace), timeout=_RPC_TIMEOUT
    )
    config = description.config
    if (
        config.history_archival_state != ArchivalState.ARCHIVAL_STATE_DISABLED
        or config.visibility_archival_state != ArchivalState.ARCHIVAL_STATE_DISABLED
        or config.history_archival_uri
        or config.visibility_archival_uri
    ):
        raise ValueError(
            "History cleanup requires archival disabled and no archive URI"
        )


class TemporalResearchHistoryPurger:
    def __init__(self, client: Client, *, page_size: int = 100) -> None:
        if not 1 <= page_size <= 1000:
            raise ValueError("History enumeration page size must be between 1 and 1000")
        self.client = client
        self.page_size = page_size

    async def purge(self, workflow_id: str) -> bool:
        prefix = "whisky-research-"
        if not workflow_id.startswith(prefix):
            raise ValueError("Only research workflow IDs may be erased")
        if workflow_id != prefix + str(UUID(workflow_id[len(prefix) :])):
            raise ValueError("Research workflow ID must contain a canonical UUID")
        await assert_namespace_without_archival(self.client)
        query = f"WorkflowId = '{workflow_id}'"
        runs = {
            execution.run_id
            async for execution in self.client.list_workflows(
                query, page_size=self.page_size, rpc_timeout=_RPC_TIMEOUT
            )
        }
        latest = self.client.get_workflow_handle(workflow_id)
        try:
            runs.add((await latest.describe(rpc_timeout=_RPC_TIMEOUT)).run_id)
        except RPCError as error:
            if error.status != RPCStatusCode.NOT_FOUND:
                raise
        for run_id in runs:
            try:
                await self.client.workflow_service.delete_workflow_execution(
                    DeleteWorkflowExecutionRequest(
                        namespace=self.client.namespace,
                        workflow_execution=WorkflowExecution(
                            workflow_id=workflow_id, run_id=run_id
                        ),
                    ),
                    timeout=_RPC_TIMEOUT,
                )
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    raise
        for run_id in runs:
            handle = self.client.get_workflow_handle(workflow_id, run_id=run_id)
            try:
                events = handle.fetch_history_events(
                    page_size=1, skip_archival=True, rpc_timeout=_RPC_TIMEOUT
                )
                await anext(events)
                return False
            except StopAsyncIteration:
                return False
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    raise
        async for _ in self.client.list_workflows(
            query, page_size=self.page_size, rpc_timeout=_RPC_TIMEOUT
        ):
            return False
        try:
            await latest.describe(rpc_timeout=_RPC_TIMEOUT)
        except RPCError as error:
            if error.status == RPCStatusCode.NOT_FOUND:
                return True
            raise
        return False
