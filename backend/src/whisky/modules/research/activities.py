"""Product DB operations used by the deterministic research workflow."""

import asyncio
from dataclasses import replace
from uuid import UUID

from sqlalchemy import Engine
from temporalio import activity
from temporalio.exceptions import ApplicationError

from whisky.modules.research.agent_v2 import PROMPT_VERSION_V2
from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.contracts import (
    AnswerReceipt,
    AnswerResult,
    PublishedQuestion,
    QuestionCommit,
    QuestionExpiry,
    ReportCommit,
    ResearchRunContext,
)
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.run_store import ResearchRunStore
from whisky.modules.research.store import ResearchConflict


class ResearchActivities:
    """One worker-owned DB boundary shared by versioned workflow activities."""

    def __init__(self, engine: Engine) -> None:
        self.run_store = ResearchRunStore(engine)
        self.clarifications = ClarificationStore(engine)
        self.reports = ReportStore(engine)

    @activity.defn(name="whisky_begin_research_v1")
    async def begin_research(self, task_id: str) -> ResearchRunContext:
        try:
            return await asyncio.to_thread(self.run_store.begin, UUID(task_id))
        except ResearchConflict as error:
            raise ApplicationError(str(error), non_retryable=True) from error

    @activity.defn(name="whisky_begin_research_v2")
    async def begin_research_v2(self, task_id: str) -> ResearchRunContext:
        context = await self.begin_research(task_id)
        return replace(context, prompt_version=PROMPT_VERSION_V2)

    @activity.defn(name="whisky_publish_question_v1")
    async def publish_question(self, commit: QuestionCommit) -> PublishedQuestion:
        try:
            return await asyncio.to_thread(
                self.clarifications.publish,
                commit.context,
                commit.waiting_version,
                commit.draft,
                commit.expires_at,
            )
        except ResearchConflict as error:
            raise ApplicationError(str(error), non_retryable=True) from error

    @activity.defn(name="whisky_accept_answer_v1")
    async def accept_answer(self, receipt: AnswerReceipt) -> AnswerResult:
        try:
            return await asyncio.to_thread(self.clarifications.accept_answer, receipt)
        except ResearchConflict as error:
            raise ApplicationError(str(error), non_retryable=True) from error

    @activity.defn(name="whisky_expire_question_v1")
    async def expire_question(self, expiry: QuestionExpiry) -> bool:
        return await asyncio.to_thread(
            self.clarifications.expire,
            expiry.context,
            expiry.question_id,
            expiry.waiting_version,
            expiry.at,
        )

    @activity.defn(name="whisky_save_report_v1")
    async def save_report(self, commit: ReportCommit) -> str:
        try:
            saved = await asyncio.to_thread(
                self.reports.save,
                commit.owner_id,
                commit.generation,
                commit.task_id,
                commit.artifact_key,
                commit.draft,
                policy_version=commit.policy_version,
                prompt_version=commit.prompt_version,
                model_version=commit.model_version,
                clarification_id=commit.clarification_id,
                selected_version_id=commit.selected_version_id,
            )
        except ResearchConflict as error:
            raise ApplicationError(str(error), non_retryable=True) from error
        return str(saved.id)

    @activity.defn(name="whisky_fail_research_v1")
    async def fail_research(self, context: ResearchRunContext) -> bool:
        return await asyncio.to_thread(self.run_store.fail, context)
