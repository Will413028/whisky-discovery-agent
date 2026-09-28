"""I/O phases for the durable control workflow."""

import asyncio
from typing import Protocol
from uuid import UUID

from temporalio import activity
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from whisky.modules.control.journal import (
    ControlJournal,
    intent_record,
    result_record,
    write_verified,
)
from whisky.modules.control.store import ControlStore


class ResearchCanceller(Protocol):
    async def cancel(self, workflow_id: str) -> None: ...


class TemporalResearchCanceller:
    def __init__(self, client: Client) -> None:
        self.client = client

    async def cancel(self, workflow_id: str) -> None:
        try:
            await self.client.get_workflow_handle(workflow_id).cancel()
        except RPCError as error:
            if error.status != RPCStatusCode.NOT_FOUND:
                raise


class ControlActivities:
    def __init__(
        self,
        store: ControlStore,
        journal: ControlJournal,
        canceller: ResearchCanceller | None = None,
    ) -> None:
        self.store = store
        self.journal = journal
        self.canceller = canceller

    @activity.defn(name="whisky_control_intent_v1")
    async def persist_intent(self, command_id: str) -> str:
        identifier = UUID(command_id)
        command = await asyncio.to_thread(self.store.load_for_activity, identifier)
        key, body = intent_record(command)
        await asyncio.to_thread(write_verified, self.journal, key, body)
        confirmed = await asyncio.to_thread(self.store.confirm_intent, identifier)
        return confirmed.status

    @activity.defn(name="whisky_control_effect_v1")
    async def apply_effect(self, command_id: str) -> str:
        applied = await asyncio.to_thread(self.store.apply, UUID(command_id))
        return applied.status

    @activity.defn(name="whisky_control_result_v1")
    async def persist_result(self, command_id: str) -> str:
        identifier = UUID(command_id)
        command = await asyncio.to_thread(self.store.load_for_activity, identifier)
        key, body = result_record(command)
        await asyncio.to_thread(write_verified, self.journal, key, body)
        confirmed = await asyncio.to_thread(self.store.confirm_result, identifier)
        return confirmed.status

    @activity.defn(name="whisky_control_notify_v1")
    async def notify_research(self, command_id: str) -> None:
        if self.canceller is None:
            return
        workflow_ids = await asyncio.to_thread(
            self.store.affected_workflows, UUID(command_id)
        )
        for workflow_id in workflow_ids:
            await self.canceller.cancel(workflow_id)
