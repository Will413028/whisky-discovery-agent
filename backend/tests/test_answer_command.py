"""Answer retries never submit a second Update after the product commit."""

from uuid import uuid4

from temporalio.service import RPCError, RPCStatusCode

from whisky.modules.research.answer import AnswerExecution, AnswerResearch
from whisky.modules.research.contracts import (
    AnswerInput,
    AnswerReceipt,
)


async def test_accepted_receipt_short_circuits_temporal_update():
    owner, task_id, question_id, command_id = (uuid4() for _ in range(4))
    receipt = AnswerReceipt(
        command_id, owner, 1, task_id, question_id, 1, 1, "15 年", "accepted"
    )

    class Store:
        def reserve_answer(self, *_args, **_kwargs):
            return receipt

    class Answerer:
        async def answer(self, _receipt):
            raise AssertionError("Temporal must not be called for a committed receipt")

    result = await AnswerResearch(Store(), Answerer()).execute(
        owner,
        1,
        AnswerInput(task_id, question_id, 1, 1, "same-key", "15 年"),
    )
    assert result == AnswerExecution(command_id, task_id, "accepted")


async def test_closed_temporal_update_reconciles_the_durable_expiry_receipt():
    owner, task_id, question_id, command_id = (uuid4() for _ in range(4))
    pending = AnswerReceipt(
        command_id, owner, 1, task_id, question_id, 1, 1, "15 年", "acceptance_pending"
    )
    rejected = AnswerReceipt(
        command_id,
        owner,
        1,
        task_id,
        question_id,
        1,
        1,
        "15 年",
        "rejected",
        "QUESTION_EXPIRED",
    )

    class Store:
        reads = 0

        def reserve_answer(self, *_args, **_kwargs):
            self.reads += 1
            return pending if self.reads == 1 else rejected

    class Answerer:
        async def answer(self, _receipt):
            raise RPCError("workflow closed", RPCStatusCode.NOT_FOUND, b"")

    result = await AnswerResearch(Store(), Answerer()).execute(
        owner, 1, AnswerInput(task_id, question_id, 1, 1, "same-key", "15 年")
    )
    assert result == AnswerExecution(
        command_id, task_id, "rejected", "QUESTION_EXPIRED"
    )
