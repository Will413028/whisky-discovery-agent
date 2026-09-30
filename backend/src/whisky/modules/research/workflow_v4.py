"""V4 structured research execution, independent of frozen older histories."""

import asyncio
import json
from datetime import timedelta
from uuid import UUID, uuid5

from pydantic_ai.durable_exec.temporal import PydanticAIWorkflow
from pydantic_ai.messages import ModelResponse
from pydantic_ai.usage import UsageLimits
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from whisky.modules.discovery.public import ExplorationIntent, ReviewedFlavorMapping
from whisky.modules.research.agent_v4 import (
    PROMPT_VERSION_V4,
    SOURCE_PROMPT_V4,
    proposal_agent_v4,
    source_agent_v4,
)
from whisky.modules.research.comparison_v4 import comparison_artifact_v4
from whisky.modules.research.contracts import (
    AnswerReceipt,
    AnswerResult,
    PublishedQuestion,
    QuestionExpiry,
    ReadSourceRequest,
    ReportCommit,
    ResearchCatalogSnapshot,
    ResearchRunContext,
    ReviewedVersionQuestionCommit,
    SourceObservationReceipt,
)
from whisky.modules.research.contracts_v4 import (
    PreferenceQuestionCommitV4,
    ReportCommitV4,
    ResearchExecutionV4,
)
from whisky.modules.research.proposal_context_v4 import ProposalContextV4
from whisky.modules.research.report import ReportCandidate, ReportDraft
from whisky.modules.research.selection_v4 import ExplorationSelection, select_research

TIMEOUT = timedelta(seconds=30)
RETRY = RetryPolicy(maximum_attempts=3)


@workflow.defn(name="ResearchWorkflowV4")
class ResearchWorkflowV4(PydanticAIWorkflow):
    __pydantic_ai_agents__ = []

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
                start_to_close_timeout=TIMEOUT,
                retry_policy=RETRY,
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
        execution = await self._begin(task_id)
        context = execution.context
        intent = execution.input.intent
        waiting_version = 0
        version_answer: AnswerReceipt | None = None
        try:
            if execution.input.phase == "proposal":
                source = execution.input.source_text
                assert source is not None
                proposal_mappings = await workflow.execute_activity(
                    "whisky_proposal_mappings_v4",
                    start_to_close_timeout=TIMEOUT,
                    retry_policy=RETRY,
                    result_type=tuple[ReviewedFlavorMapping, ...],
                )
                proposal_context = ProposalContextV4(source, proposal_mappings)
                result = await proposal_agent_v4().run(
                    json.dumps(
                        {
                            "source_text": source,
                            "reviewed_mappings": [
                                mapping.model_dump(mode="json")
                                for mapping in proposal_context.mappings
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    deps=proposal_context,
                    usage_limits=UsageLimits(
                        request_limit=2,
                        total_tokens_limit=4000,
                        output_tokens_limit=2000,
                    ),
                )
                waiting_version += 1
                question = await workflow.execute_activity(
                    "whisky_publish_preference_question_v4",
                    PreferenceQuestionCommitV4(
                        context,
                        waiting_version,
                        source,
                        result.output,
                        workflow.now() + timedelta(days=7),
                    ),
                    start_to_close_timeout=TIMEOUT,
                    retry_policy=RETRY,
                    result_type=PublishedQuestion,
                )
                reply = await self._wait(context, question)
                if reply is None:
                    return "expired"
                if reply.answer == str(uuid5(self.task_id, "proposal:use-intent")):
                    intent = result.output.intent
                context = (await self._begin(task_id)).context
            for _ in range(3):
                snapshot = await workflow.execute_activity(
                    "whisky_catalog_snapshot_v3",
                    context,
                    start_to_close_timeout=TIMEOUT,
                    retry_policy=RETRY,
                    result_type=ResearchCatalogSnapshot,
                )
                selection = select_research(
                    context.conditions,
                    snapshot,
                    version_answer.answer if version_answer else None,
                    intent=intent,
                )
                if selection.version_indices:
                    if snapshot.release_id is None:
                        raise ValueError("Reviewed versions require a release")
                    if waiting_version >= (
                        3 if execution.input.phase == "proposal" else 2
                    ):
                        raise ValueError("Research exceeded its clarification limit")
                    waiting_version += 1
                    question = await workflow.execute_activity(
                        "whisky_publish_question_v4",
                        ReviewedVersionQuestionCommit(
                            context,
                            waiting_version,
                            snapshot.release_id,
                            tuple(
                                snapshot.items[index - 1].bottle_version_id
                                for index in selection.version_indices
                            ),
                            workflow.now() + timedelta(days=7),
                        ),
                        start_to_close_timeout=TIMEOUT,
                        retry_policy=RETRY,
                        result_type=PublishedQuestion,
                    )
                    version_answer = await self._wait(context, question)
                    if version_answer is None:
                        return "expired"
                    context = (await self._begin(task_id)).context
                    continue
                report, model_name, observations = await self._report(
                    context, snapshot, selection, intent
                )
                saved = await workflow.execute_activity(
                    "whisky_save_report_v4",
                    ReportCommitV4(
                        ReportCommit(
                            self.task_id,
                            context.owner_id,
                            context.generation,
                            f"final:v4:{task_id}",
                            report,
                            context.policy_version,
                            context.prompt_version,
                            model_name,
                            version_answer.question_id if version_answer else None,
                            UUID(version_answer.answer) if version_answer else None,
                            observations,
                        ),
                        comparison_artifact_v4(
                            context.conditions,
                            snapshot,
                            version_answer.answer if version_answer else None,
                            intent,
                            selection,
                        ),
                    ),
                    start_to_close_timeout=TIMEOUT,
                    retry_policy=RETRY,
                    result_type=str,
                )
                self.closed = True
                await workflow.wait_condition(workflow.all_handlers_finished)
                return saved
            raise ValueError("Research did not produce a report")
        except Exception as error:
            self.closed = True
            await workflow.execute_activity(
                "whisky_fail_research_v1",
                context,
                start_to_close_timeout=TIMEOUT,
                retry_policy=RETRY,
                result_type=bool,
            )
            await workflow.wait_condition(workflow.all_handlers_finished)
            raise ApplicationError("RESEARCH_FAILED", non_retryable=True) from error

    async def _begin(self, task_id: str) -> ResearchExecutionV4:
        execution = await workflow.execute_activity(
            "whisky_begin_research_v4",
            task_id,
            start_to_close_timeout=TIMEOUT,
            retry_policy=RETRY,
            result_type=ResearchExecutionV4,
        )
        if execution.context.prompt_version != PROMPT_VERSION_V4:
            raise ApplicationError("V4 prompt version changed", non_retryable=True)
        return execution

    async def _wait(
        self, context: ResearchRunContext, question: PublishedQuestion
    ) -> AnswerReceipt | None:
        self.pending = question
        self.received_answer = None
        try:
            await workflow.wait_condition(
                lambda: self.received_answer is not None,
                timeout=question.expires_at - workflow.now(),
            )
        except TimeoutError:
            expired = await workflow.execute_activity(
                "whisky_expire_question_v1",
                QuestionExpiry(
                    context, question.id, question.waiting_version, workflow.now()
                ),
                start_to_close_timeout=TIMEOUT,
                retry_policy=RETRY,
                result_type=bool,
            )
            if expired:
                self.closed = True
                await workflow.wait_condition(workflow.all_handlers_finished)
                return None
            await workflow.wait_condition(lambda: self.received_answer is not None)
        reply = self.received_answer
        self.pending = None
        return reply

    async def _report(
        self,
        context: ResearchRunContext,
        snapshot: ResearchCatalogSnapshot,
        selection: ExplorationSelection,
        intent: ExplorationIntent,
    ) -> tuple[ReportDraft, str, tuple[UUID, ...]]:
        if selection.unlisted_name is not None:
            return (
                ReportDraft(
                    f"「{selection.unlisted_name}」不在本版已覆核酒款中，無法提供有來源的版本或比較。",
                    (),
                    ("可改從已收錄酒款或具體風味條件繼續探索。",),
                ),
                "catalog-coverage-rule-v4",
                (),
            )
        if not selection.candidate_indices:
            return (
                ReportDraft(
                    "目前已覆核酒款沒有同時符合本次預算與探索方向的候選。",
                    (),
                    selection.unresolved,
                ),
                "catalog-selection-rule-v4",
                (),
            )
        candidates = tuple(
            snapshot.items[index - 1] for index in selection.candidate_indices
        )
        remaining = [
            source
            for source in snapshot.sources
            if source.item_index in selection.candidate_indices
        ]
        if not remaining:
            raise ValueError("Research candidates have no reviewed source")
        observations = []
        unresolved = list(selection.unresolved)
        model_name = "unknown-model"
        for _ in range(min(2, len(remaining))):
            result = await source_agent_v4().run(
                SOURCE_PROMPT_V4
                + json.dumps(
                    {
                        "intent": intent.model_dump(mode="json"),
                        "candidates": [
                            {
                                "name": item.name,
                                "version": item.version_label,
                                "tags": item.flavor_tags,
                            }
                            for item in candidates
                        ],
                        "provided_sources": [
                            {
                                "index": source.index,
                                "item_name": snapshot.items[source.item_index - 1].name,
                                "publisher": source.publisher,
                            }
                            for source in remaining
                        ],
                    },
                    ensure_ascii=False,
                ),
                usage_limits=UsageLimits(
                    request_limit=2, total_tokens_limit=4000, output_tokens_limit=2000
                ),
            )
            source = next(
                (
                    value
                    for value in remaining
                    if value.index == result.output.source_index
                ),
                None,
            )
            if source is None:
                raise ValueError("INVALID_SOURCE_CHOICE")
            remaining.remove(source)
            observed = await workflow.execute_activity(
                "whisky_read_source_v3",
                ReadSourceRequest(context, source),
                start_to_close_timeout=TIMEOUT,
                retry_policy=RETRY,
                result_type=SourceObservationReceipt,
            )
            if observed.id is not None:
                observations.append(observed.id)
            model_name = (
                next(
                    (
                        message.model_name
                        for message in reversed(result.all_messages())
                        if isinstance(message, ModelResponse)
                    ),
                    None,
                )
                or "unknown-model"
            )
            if observed.status == "ok":
                break
            unresolved.append(
                f"指定來源暫時無法讀取（{observed.code}）；仍以已覆核資料為準。"
            )
        names = "、".join(f"「{item.name}」" for item in candidates)
        report = ReportDraft(
            f"依目前已覆核資料找到 {len(candidates)} 款候選：{names}。",
            tuple(
                ReportCandidate(
                    item.release_id,
                    item.item_id,
                    item.claims,
                    "品牌描述："
                    + (item.tasting_notes or "尚無可引用的風味描述")
                    + "；編輯整理標籤："
                    + "、".join(item.flavor_tags),
                    item.price_ids,
                )
                for item in candidates
            ),
            tuple(unresolved),
        )
        return report, model_name, tuple(observations)
