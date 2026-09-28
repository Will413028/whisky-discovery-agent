"""Reconcile a committed product receipt with Temporal service acceptance."""

import asyncio
from typing import Protocol
from uuid import UUID

from temporalio.service import RPCError, RPCStatusCode

from whisky.modules.research.store import ResearchStore, StartReceipt


class ResearchStarter(Protocol):
    async def start(self, task_id: UUID) -> str: ...


class AcceptResearch:
    def __init__(self, store: ResearchStore, starter: ResearchStarter) -> None:
        self.store = store
        self.starter = starter

    async def execute(
        self, owner: UUID, generation: int, plan_id: UUID, revision: int, key: str
    ) -> StartReceipt:
        receipt = await asyncio.to_thread(
            self.store.reserve, owner, generation, plan_id, revision, key
        )
        if receipt.acceptance == "accepted":
            return receipt
        try:
            run_id = await self.starter.start(receipt.task_id)
        except TimeoutError:
            return receipt
        except RPCError as error:
            if error.status in {
                RPCStatusCode.UNAVAILABLE,
                RPCStatusCode.DEADLINE_EXCEEDED,
                RPCStatusCode.UNKNOWN,
                RPCStatusCode.RESOURCE_EXHAUSTED,
            }:
                return receipt
            raise
        return await asyncio.to_thread(
            self.store.confirm, owner, generation, receipt.id, run_id
        )
