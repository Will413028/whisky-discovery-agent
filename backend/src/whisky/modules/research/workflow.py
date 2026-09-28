"""Deterministic coordinator for one durable research task."""

from datetime import timedelta
from uuid import UUID

from pydantic_ai.durable_exec.temporal import PydanticAIWorkflow
from pydantic_ai.messages import ModelResponse, ToolReturnPart
from pydantic_ai.usage import UsageLimits
from temporalio import workflow
from temporalio.common import RetryPolicy

from whisky.modules.research.agent import (
    PROMPT_VERSION,
    ResearchAgentDeps,
    research_agent,
)
from whisky.modules.research.contracts import ReportCommit, ResearchRunContext


@workflow.defn(name="ResearchWorkflow")
class ResearchWorkflow(PydanticAIWorkflow):
    __pydantic_ai_agents__ = []  # Registered by worker setup after model selection.

    @workflow.run
    async def run(self, task_id: str) -> str:
        context = await workflow.execute_activity(
            "whisky_begin_research_v1",
            task_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
            result_type=ResearchRunContext,
        )
        try:
            if context.prompt_version != PROMPT_VERSION:
                raise ValueError("Research prompt version changed during workflow")
            conditions = context.conditions
            result = await research_agent().run(
                (
                    f"Research goal: {conditions.goal}. Entry: {conditions.entry}. "
                    f"Preferences: {conditions.preferences}. "
                    f"Starting bottle: {conditions.starting_bottle}. "
                    f"Budget TWD: {conditions.budget_twd}."
                ),
                deps=ResearchAgentDeps(context.as_of, conditions.budget_twd),
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
                raise ValueError(
                    "Research requires a completed reviewed catalog lookup"
                )
            model_response = next(
                message
                for message in reversed(result.all_messages())
                if isinstance(message, ModelResponse)
            )
            commit = ReportCommit(
                UUID(task_id),
                context.owner_id,
                context.generation,
                f"final:v1:{task_id}",
                result.output,
                context.policy_version,
                context.prompt_version,
                model_response.model_name or "unknown-model",
            )
            return await workflow.execute_activity(
                "whisky_save_report_v1",
                commit,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
                result_type=str,
            )
        except Exception:
            await workflow.execute_activity(
                "whisky_fail_research_v1",
                context,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
                result_type=bool,
            )
            raise
