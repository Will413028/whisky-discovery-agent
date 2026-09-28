"""Product DB operations used by the deterministic research workflow."""

import asyncio
from uuid import UUID

from temporalio import activity
from temporalio.exceptions import ApplicationError

from whisky.modules.research.agent import configured_engine
from whisky.modules.research.contracts import ReportCommit, ResearchRunContext
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.run_store import ResearchRunStore
from whisky.modules.research.store import ResearchConflict


@activity.defn(name="whisky_begin_research_v1")
async def begin_research(task_id: str) -> ResearchRunContext:
    try:
        return await asyncio.to_thread(
            ResearchRunStore(configured_engine()).begin, UUID(task_id)
        )
    except ResearchConflict as error:
        raise ApplicationError(str(error), non_retryable=True) from error


@activity.defn(name="whisky_save_report_v1")
async def save_report(commit: ReportCommit) -> str:
    try:
        saved = await asyncio.to_thread(
            ReportStore(configured_engine()).save,
            commit.owner_id,
            commit.generation,
            commit.task_id,
            commit.artifact_key,
            commit.draft,
            policy_version=commit.policy_version,
            prompt_version=commit.prompt_version,
            model_version=commit.model_version,
        )
    except ResearchConflict as error:
        raise ApplicationError(str(error), non_retryable=True) from error
    return str(saved.id)


@activity.defn(name="whisky_fail_research_v1")
async def fail_research(context: ResearchRunContext) -> bool:
    return await asyncio.to_thread(ResearchRunStore(configured_engine()).fail, context)
