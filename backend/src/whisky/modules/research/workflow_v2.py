"""Durable research with a versioned human wait and fresh post-answer lookup."""

import asyncio
from datetime import timedelta
from uuid import UUID

from pydantic_ai.durable_exec.temporal import PydanticAIWorkflow
from pydantic_ai.messages import ModelResponse, ToolReturnPart
from pydantic_ai.usage import UsageLimits
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from whisky.modules.research.agent_v2 import (
    PROMPT_VERSION_V2,
    ResearchAgentDepsV2,
    research_agent_v2,
)
from whisky.modules.research.contracts import (
    AnswerReceipt,
    AnswerResult,
    PublishedQuestion,
    QuestionCommit,
    QuestionExpiry,
    ReportCommit,
    ResearchRunContext,
)
from whisky.modules.research.decision import ResearchDecision


@workflow.defn(name="ResearchWorkflowV2")
class ResearchWorkflowV2(PydanticAIWorkflow):
    __pydantic_ai_agents__ = []  # Bound once by worker setup.

    @workflow.init
    def __init__(self, task_id: str) -> None:
        self.task_id = UUID(task_id)
        self.pending: PublishedQuestion | None = None
        self.received_answer: AnswerReceipt | None = None
        self.closed = False
        self.update_lock = asyncio.Lock()

    @workflow.update(name="answer")
    async def answer(self, receipt: AnswerReceipt) -> AnswerResult:
        async with self.update_lock:
            await workflow.wait_condition(
                lambda: self.pending is not None or self.closed
            )
            result = await workflow.execute_activity(
                "whisky_accept_answer_v1",
                receipt,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
                result_type=AnswerResult,
            )
            if result.acceptance == "accepted" and self.pending is not None:
                if receipt.question_id == self.pending.id:
                    self.received_answer = receipt
            return result

    @answer.validator
    def validate_answer(self, receipt: AnswerReceipt) -> None:
        if (
            receipt.task_id != self.task_id
            or receipt.waiting_version < 1
            or not receipt.answer.strip()
        ):
            raise ValueError("INVALID_ANSWER")

    @workflow.run
    async def run(self, task_id: str) -> str:
        context = await self._begin(task_id)
        answered: list[tuple[UUID, str, str]] = []
        waiting_version = 0
        try:
            for _ in range(3):
                decision, model_name = await self._decide(context, answered)
                decision.selected()
                if decision.report is not None:
                    commit = ReportCommit(
                        self.task_id,
                        context.owner_id,
                        context.generation,
                        f"final:v2:{task_id}",
                        decision.report,
                        context.policy_version,
                        context.prompt_version,
                        model_name,
                        answered[-1][0] if answered else None,
                        UUID(answered[-1][2]) if answered else None,
                    )
                    saved = await workflow.execute_activity(
                        "whisky_save_report_v1",
                        commit,
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                        result_type=str,
                    )
                    self.closed = True
                    await workflow.wait_condition(workflow.all_handlers_finished)
                    return saved
                if decision.clarification is None or waiting_version >= 2:
                    raise ValueError("Research exceeded its clarification limit")
                selected = decision.clarification
                waiting_version += 1
                expires_at = workflow.now() + timedelta(days=7)
                question = await workflow.execute_activity(
                    "whisky_publish_question_v1",
                    QuestionCommit(context, waiting_version, selected, expires_at),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                    result_type=PublishedQuestion,
                )
                self.pending = question
                self.received_answer = None
                try:
                    await workflow.wait_condition(
                        lambda: self.received_answer is not None,
                        timeout=expires_at - workflow.now(),
                    )
                except TimeoutError:
                    expired = await workflow.execute_activity(
                        "whisky_expire_question_v1",
                        QuestionExpiry(
                            context, question.id, waiting_version, workflow.now()
                        ),
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                        result_type=bool,
                    )
                    if expired:
                        self.closed = True
                        await workflow.wait_condition(workflow.all_handlers_finished)
                        return "expired"
                    await workflow.wait_condition(
                        lambda: self.received_answer is not None
                    )
                assert self.received_answer is not None
                answered.append(
                    (question.id, selected.prompt, self.received_answer.answer)
                )
                self.pending = None
                context = await self._begin(task_id)
            raise ValueError("Research did not produce a report")
        except Exception as error:
            self.closed = True
            await workflow.execute_activity(
                "whisky_fail_research_v1",
                context,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
                result_type=bool,
            )
            await workflow.wait_condition(workflow.all_handlers_finished)
            raise ApplicationError("RESEARCH_FAILED", non_retryable=True) from error

    async def _begin(self, task_id: str) -> ResearchRunContext:
        context = await workflow.execute_activity(
            "whisky_begin_research_v2",
            task_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
            result_type=ResearchRunContext,
        )
        if context.prompt_version != PROMPT_VERSION_V2:
            raise ApplicationError(
                "Research prompt version changed during workflow", non_retryable=True
            )
        return context

    async def _decide(
        self, context: ResearchRunContext, answered: list[tuple[UUID, str, str]]
    ) -> tuple[ResearchDecision, str]:
        conditions = context.conditions
        prior_answers = "; ".join(
            f"Question: {question} Selected reviewed bottle version ID: {answer}"
            for _, question, answer in answered
        )
        result = await research_agent_v2().run(
            (
                f"Research goal: {conditions.goal}. Entry: {conditions.entry}. "
                f"Preferences: {conditions.preferences}. "
                f"Starting bottle: {conditions.starting_bottle}. "
                f"Budget TWD: {conditions.budget_twd}. "
                f"Previously clarified: {prior_answers}."
            ),
            deps=ResearchAgentDepsV2(
                context.as_of,
                conditions.budget_twd,
                answered[-1][2] if answered else None,
            ),
            usage_limits=UsageLimits(
                request_limit=4,
                tool_calls_limit=2,
                total_tokens_limit=12000,
                output_tokens_limit=4000,
            ),
        )
        if not any(
            isinstance(part, ToolReturnPart)
            and part.tool_name == "search_reviewed_catalog"
            for message in result.all_messages()
            for part in message.parts
        ):
            raise ValueError("Research requires a completed reviewed catalog lookup")
        model_response = next(
            message
            for message in reversed(result.all_messages())
            if isinstance(message, ModelResponse)
        )
        return result.output, model_response.model_name or "unknown-model"
