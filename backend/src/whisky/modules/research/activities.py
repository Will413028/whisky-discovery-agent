"""Product DB operations used by the deterministic research workflow."""

import asyncio
import time
from dataclasses import replace
from uuid import UUID

from sqlalchemy import Engine
from temporalio import activity
from temporalio.exceptions import ApplicationError

from whisky.modules.catalog.public import (
    current_release_id,
    published_source,
    reviewed_catalog_snapshot,
    reviewed_flavor_references,
)
from whisky.modules.discovery.public import ReviewedFlavorMapping
from whisky.modules.research.agent_v2 import PROMPT_VERSION_V2
from whisky.modules.research.agent_v3 import PROMPT_VERSION_V3
from whisky.modules.research.agent_v4 import PROMPT_VERSION_V4
from whisky.modules.research.catalog_snapshot import research_catalog_snapshot
from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.contracts import (
    AnswerReceipt,
    AnswerResult,
    PublishedQuestion,
    QuestionCommit,
    QuestionExpiry,
    ReadSourceRequest,
    ReportCommit,
    ResearchCatalogSnapshot,
    ResearchRunContext,
    ReviewedVersionQuestionCommit,
    SourceObservation,
    SourceObservationReceipt,
)
from whisky.modules.research.contracts_v4 import (
    PreferenceQuestionCommitV4,
    ReportCommitV4,
    ResearchExecutionV4,
)
from whisky.modules.research.proposal_context_v4 import proposal_context_v4
from whisky.modules.research.quota import QuotaError, QuotaStore
from whisky.modules.research.report_store import ReportStore
from whisky.modules.research.run_store import ResearchRunStore
from whisky.modules.research.source_observation import SourceObservationStore
from whisky.modules.research.source_reader import SourceReader, SourceReadError
from whisky.modules.research.store import ResearchConflict


class ResearchActivities:
    """One worker-owned DB boundary shared by versioned workflow activities."""

    def __init__(
        self,
        engine: Engine,
        *,
        quota: QuotaStore | None = None,
        source_reader: SourceReader | None = None,
    ) -> None:
        self.engine = engine
        self.quota = quota
        self.source_reader = source_reader or SourceReader()
        self.observations = SourceObservationStore(engine)
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

    @activity.defn(name="whisky_begin_research_v3")
    async def begin_research_v3(self, task_id: str) -> ResearchRunContext:
        context = await self.begin_research(task_id)
        return replace(context, prompt_version=PROMPT_VERSION_V3)

    @activity.defn(name="whisky_begin_research_v4")
    async def begin_research_v4(self, task_id: str) -> ResearchExecutionV4:
        try:
            return await asyncio.to_thread(
                self.run_store.begin_v4, UUID(task_id), PROMPT_VERSION_V4
            )
        except (ResearchConflict, ValueError) as error:
            raise ApplicationError(str(error), non_retryable=True) from error

    @activity.defn(name="whisky_publish_preference_question_v4")
    async def publish_preference_question_v4(
        self, commit: PreferenceQuestionCommitV4
    ) -> PublishedQuestion:
        try:
            return await asyncio.to_thread(
                self.clarifications.publish_preference_proposal,
                commit.context,
                commit.waiting_version,
                commit.source_text,
                commit.proposal,
                commit.expires_at,
            )
        except (ResearchConflict, ValueError) as error:
            raise ApplicationError(str(error), non_retryable=True) from error

    @activity.defn(name="whisky_catalog_snapshot_v3")
    async def catalog_snapshot_v3(
        self, context: ResearchRunContext
    ) -> ResearchCatalogSnapshot:
        return await asyncio.to_thread(self._catalog_snapshot, context)

    @activity.defn(name="whisky_proposal_mappings_v4")
    async def proposal_mappings_v4(self) -> tuple[ReviewedFlavorMapping, ...]:
        return await asyncio.to_thread(self._proposal_mappings_v4)

    def _proposal_mappings_v4(self) -> tuple[ReviewedFlavorMapping, ...]:
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            references = reviewed_flavor_references(
                connection, current_release_id(connection)
            )
            return proposal_context_v4("", references).mappings

    def _catalog_snapshot(self, context: ResearchRunContext) -> ResearchCatalogSnapshot:
        catalog = reviewed_catalog_snapshot(
            self.engine, context.as_of, context.conditions.budget_twd
        )
        return research_catalog_snapshot(catalog)

    @activity.defn(name="whisky_read_source_v3")
    async def read_source_v3(
        self, request: ReadSourceRequest
    ) -> SourceObservationReceipt:
        selected = request.source
        with self.engine.connect() as connection:
            if current_release_id(connection) != selected.release_id:
                return SourceObservationReceipt("unavailable", "SOURCE_NOT_CURRENT")
            source = published_source(
                connection,
                selected.release_id,
                selected.evidence_id,
                selected.bottle_version_id,
            )
        if source is None:
            return SourceObservationReceipt("unavailable", "SOURCE_NOT_REVIEWED")
        reservation = None
        quota = self.quota
        if quota is not None:
            workflow_id = activity.info().workflow_id or ""
            prefix = "whisky-research-"
            if not workflow_id.startswith(prefix):
                raise ApplicationError("INVALID_RESEARCH_WORKFLOW", non_retryable=True)
            try:
                reservation = await asyncio.to_thread(
                    quota.reserve,
                    UUID(workflow_id.removeprefix(prefix)),
                    activity.info().activity_id,
                    activity.info().attempt,
                    "reader",
                    0,
                    0,
                )
            except QuotaError as error:
                raise ApplicationError(error.code, non_retryable=True) from error
        started = time.monotonic()
        known = False
        try:
            try:
                page = await self.source_reader.read(source.url)
            except SourceReadError as error:
                known = True
                if error.retryable and activity.info().attempt < 3:
                    raise
                observation = SourceObservation("unavailable", error.code)
                return await self._save_source_observation(request, observation)
            known = True
            observation = SourceObservation(
                "ok",
                text=page.text,
                checked_on=source.checked_on,
                final_url=page.final_url,
            )
            return await self._save_source_observation(request, observation)
        finally:
            if reservation is not None:
                assert quota is not None
                await asyncio.to_thread(
                    quota.finish,
                    reservation.id,
                    known=known,
                    latency_ms=int((time.monotonic() - started) * 1000),
                )

    async def _save_source_observation(
        self, request: ReadSourceRequest, observation: SourceObservation
    ) -> SourceObservationReceipt:
        try:
            return await asyncio.to_thread(
                self.observations.save,
                request,
                activity.info().activity_id,
                observation,
            )
        except (ResearchConflict, ValueError) as error:
            raise ApplicationError(str(error), non_retryable=True) from error

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
        except (ResearchConflict, ValueError) as error:
            raise ApplicationError(str(error), non_retryable=True) from error

    @activity.defn(name="whisky_publish_question_v3")
    async def publish_question_v3(
        self, commit: ReviewedVersionQuestionCommit
    ) -> PublishedQuestion:
        try:
            return await asyncio.to_thread(
                self.clarifications.publish_reviewed_versions,
                commit.context,
                commit.waiting_version,
                commit.version_ids,
                commit.expires_at,
                commit.release_id,
            )
        except (ResearchConflict, ValueError) as error:
            raise ApplicationError(str(error), non_retryable=True) from error

    @activity.defn(name="whisky_publish_question_v4")
    async def publish_question_v4(
        self, commit: ReviewedVersionQuestionCommit
    ) -> PublishedQuestion:
        try:
            return await asyncio.to_thread(
                self.clarifications.publish_reviewed_versions_v4,
                commit.context,
                commit.waiting_version,
                commit.version_ids,
                commit.expires_at,
                commit.release_id,
            )
        except (ResearchConflict, ValueError) as error:
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
                source_observation_ids=commit.source_observation_ids,
            )
        except ResearchConflict as error:
            raise ApplicationError(str(error), non_retryable=True) from error
        return str(saved.id)

    @activity.defn(name="whisky_save_report_v4")
    async def save_report_v4(self, commit: ReportCommitV4) -> str:
        try:
            saved = await asyncio.to_thread(
                self.reports.save_v4, commit.report, commit.comparison
            )
        except (ResearchConflict, ValueError) as error:
            raise ApplicationError(str(error), non_retryable=True) from error
        return str(saved.id)

    @activity.defn(name="whisky_fail_research_v1")
    async def fail_research(self, context: ResearchRunContext) -> bool:
        return await asyncio.to_thread(self.run_store.fail, context)
