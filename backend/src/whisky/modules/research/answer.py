"""Reconcile a durable answer command with one Temporal Update."""

import asyncio
import math
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from temporalio.service import RPCError, RPCStatusCode

from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.contracts import (
    AnswerInput,
    AnswerReceipt,
    AnswerResult,
)


class ResearchAnswerer(Protocol):
    async def answer(self, receipt: AnswerReceipt) -> AnswerResult: ...


@dataclass(frozen=True)
class AnswerExecution:
    command_id: UUID
    task_id: UUID
    acceptance: Literal["acceptance_pending", "accepted", "rejected"]
    code: str | None = None


class AnswerResearch:
    def __init__(
        self, store: ClarificationStore, answerer: ResearchAnswerer, timeout: float = 10
    ) -> None:
        self.store = store
        self.answerer = answerer
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Answer timeout must be positive and finite")
        self.timeout = timeout

    async def execute(
        self, owner: UUID, generation: int, command: AnswerInput
    ) -> AnswerExecution:
        receipt = await self._receipt(owner, generation, command)
        if receipt.acceptance == "accepted":
            return AnswerExecution(receipt.id, receipt.task_id, "accepted")
        if receipt.acceptance == "rejected":
            return AnswerExecution(
                receipt.id, receipt.task_id, "rejected", receipt.code
            )
        try:
            async with asyncio.timeout(self.timeout):
                result = await self.answerer.answer(receipt)
        except TimeoutError:
            return AnswerExecution(receipt.id, receipt.task_id, "acceptance_pending")
        except RPCError as error:
            if error.status == RPCStatusCode.NOT_FOUND:
                current = await self._receipt(owner, generation, command)
                return AnswerExecution(
                    current.id, current.task_id, current.acceptance, current.code
                )
            if error.status in {
                RPCStatusCode.UNAVAILABLE,
                RPCStatusCode.DEADLINE_EXCEEDED,
                RPCStatusCode.UNKNOWN,
                RPCStatusCode.RESOURCE_EXHAUSTED,
            }:
                return AnswerExecution(
                    receipt.id, receipt.task_id, "acceptance_pending"
                )
            raise
        return AnswerExecution(
            receipt.id, receipt.task_id, result.acceptance, result.code
        )

    async def _receipt(
        self, owner: UUID, generation: int, command: AnswerInput
    ) -> AnswerReceipt:
        return await asyncio.to_thread(
            self.store.reserve_answer,
            owner,
            generation,
            command.task_id,
            command.question_id,
            command.waiting_version,
            command.conditions_revision,
            command.key,
            command.answer,
            thread_id=command.thread_id,
            run_id=command.run_id,
        )
