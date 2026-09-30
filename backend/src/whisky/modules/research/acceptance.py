"""Reconcile a committed product receipt with Temporal service acceptance."""

import asyncio
import math
from typing import Protocol
from uuid import UUID

from temporalio.service import RPCError, RPCStatusCode

from whisky.modules.research.commands import StartTurn
from whisky.modules.research.inputs_v4 import StartTurnV4
from whisky.modules.research.store import ResearchStore, StartReceipt


class ResearchStarter(Protocol):
    async def start(self, task_id: UUID) -> str: ...


class AcceptResearch:
    def __init__(
        self, store: ResearchStore, starter: ResearchStarter, start_timeout: float = 10
    ) -> None:
        if not math.isfinite(start_timeout) or start_timeout <= 0:
            raise ValueError("Temporal start timeout must be positive and finite")
        self.store = store
        self.starter = starter
        self.start_timeout = start_timeout

    async def execute(
        self, owner: UUID, generation: int, plan_id: UUID, revision: int, key: str
    ) -> StartReceipt:
        receipt = await asyncio.to_thread(
            self.store.reserve, owner, generation, plan_id, revision, key
        )
        return await self._accept(owner, generation, receipt)

    async def execute_turn(
        self, owner: UUID, generation: int, turn: StartTurn | StartTurnV4
    ) -> StartReceipt:
        if isinstance(turn, StartTurnV4):
            receipt = await asyncio.to_thread(
                self.store.reserve_turn_v4, owner, generation, turn
            )
        else:
            receipt = await asyncio.to_thread(
                self.store.reserve_turn, owner, generation, turn
            )
        return await self._accept(owner, generation, receipt)

    async def _accept(
        self, owner: UUID, generation: int, receipt: StartReceipt
    ) -> StartReceipt:
        if receipt.acceptance == "accepted":
            return receipt
        try:
            async with asyncio.timeout(self.start_timeout):
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
