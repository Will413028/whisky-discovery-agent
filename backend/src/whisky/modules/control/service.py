"""Reconcile one typed control command across HTTP retries and Temporal."""

import asyncio
import math
from typing import Protocol
from uuid import UUID

from temporalio.service import RPCError, RPCStatusCode

from whisky.modules.control.store import (
    ControlKind,
    ControlReceipt,
    ControlStore,
)
from whisky.modules.discovery.public import ResearchConditions


class ControlStarter(Protocol):
    async def start(self, receipt: ControlReceipt) -> str | None: ...


class ControlController:
    def __init__(
        self, store: ControlStore, starter: ControlStarter, start_timeout: float = 10
    ) -> None:
        if not math.isfinite(start_timeout) or start_timeout <= 0:
            raise ValueError("Temporal start timeout must be positive and finite")
        self.store = store
        self.starter = starter
        self.start_timeout = start_timeout

    async def execute(
        self,
        owner: UUID,
        generation: int,
        kind: ControlKind,
        target_id: UUID,
        key: str,
        *,
        expected_revision: int = 0,
        conditions: ResearchConditions | None = None,
    ) -> ControlReceipt:
        receipt = await asyncio.to_thread(
            self.store.reserve,
            owner,
            generation,
            kind,
            target_id,
            key,
            expected_revision=expected_revision,
            conditions=conditions,
        )
        if receipt.status not in {"completed", "rejected"}:
            try:
                async with asyncio.timeout(self.start_timeout):
                    await self.starter.start(receipt)
            except TimeoutError:
                pass
            except RPCError as error:
                if error.status not in {
                    RPCStatusCode.UNAVAILABLE,
                    RPCStatusCode.DEADLINE_EXCEEDED,
                    RPCStatusCode.UNKNOWN,
                    RPCStatusCode.RESOURCE_EXHAUSTED,
                }:
                    raise
        latest = await asyncio.to_thread(self.store.read, receipt.id, owner)
        assert latest is not None
        return latest
