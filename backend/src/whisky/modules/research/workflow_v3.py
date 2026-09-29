"""Durable research with rule-qualified candidates and bounded model choice."""

import asyncio
import json
from datetime import timedelta
from uuid import UUID

from pydantic_ai.durable_exec.temporal import PydanticAIWorkflow
from pydantic_ai.messages import ModelResponse
from pydantic_ai.usage import UsageLimits
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from whisky.modules.research.agent_v3 import (
    PROMPT_VERSION_V3,
    SOURCE_CHOICE_PROMPT_V3,
    research_agent_v3,
)
from whisky.modules.research.contracts import (
    AnswerReceipt,
    AnswerResult,
    PublishedQuestion,
    QuestionExpiry,
    ReadSourceRequest,
    ReportCommit,
    ResearchCatalogItem,
    ResearchCatalogSnapshot,
    ResearchRunContext,
    ReviewedVersionQuestionCommit,
    SourceObservationReceipt,
)
from whisky.modules.research.decision import ResearchDecision
from whisky.modules.research.report import ReportCandidate, ReportDraft
from whisky.modules.research.selection_v3 import ResearchSelection, select_research


@workflow.defn(name="ResearchWorkflowV3")
class ResearchWorkflowV3(PydanticAIWorkflow):
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
        answered: list[tuple[UUID, str]] = []
        waiting_version = 0
        try:
            for _ in range(3):
                snapshot = await workflow.execute_activity(
                    "whisky_catalog_snapshot_v3",
                    context,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                    result_type=ResearchCatalogSnapshot,
                )
                selection = select_research(
                    context.conditions,
                    snapshot,
                    answered[-1][1] if answered else None,
                )
                source_observation_id = None
                if selection.version_indices:
                    version_ids = _version_choices(snapshot, selection.version_indices)
                    decision = None
                elif selection.unlisted_name is not None:
                    version_ids = None
                    decision = ResearchDecision(
                        report=_unlisted_report(selection.unlisted_name)
                    )
                    model_name = "catalog-coverage-rule-v1"
                elif not selection.candidate_indices:
                    version_ids = None
                    decision = ResearchDecision(
                        report=_empty_budget_report(context, snapshot, selection)
                    )
                    model_name = "catalog-budget-rule-v1"
                else:
                    version_ids = None
                    decision, model_name, source_observation_id = await self._decide(
                        context, snapshot, selection, answered
                    )
                if decision is not None:
                    decision.selected()
                if decision is not None and decision.report is not None:
                    commit = ReportCommit(
                        self.task_id,
                        context.owner_id,
                        context.generation,
                        f"final:v3:{task_id}",
                        decision.report,
                        context.policy_version,
                        context.prompt_version,
                        model_name,
                        answered[-1][0] if answered else None,
                        UUID(answered[-1][1]) if answered else None,
                        (source_observation_id,)
                        if source_observation_id is not None
                        else (),
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
                if version_ids is None or waiting_version >= 2:
                    raise ValueError("Research exceeded its clarification limit")
                waiting_version += 1
                expires_at = workflow.now() + timedelta(days=7)
                if snapshot.release_id is None:
                    raise ValueError(
                        "Reviewed version choices require a catalog release"
                    )
                question = await workflow.execute_activity(
                    "whisky_publish_question_v3",
                    ReviewedVersionQuestionCommit(
                        context,
                        waiting_version,
                        snapshot.release_id,
                        version_ids,
                        expires_at,
                    ),
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
                answered.append((question.id, self.received_answer.answer))
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
            "whisky_begin_research_v3",
            task_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
            result_type=ResearchRunContext,
        )
        if context.prompt_version != PROMPT_VERSION_V3:
            raise ApplicationError(
                "Research prompt version changed during workflow", non_retryable=True
            )
        return context

    async def _decide(
        self,
        context: ResearchRunContext,
        snapshot: ResearchCatalogSnapshot,
        selection: ResearchSelection,
        answered: list[tuple[UUID, str]],
    ) -> tuple[ResearchDecision, str, UUID | None]:
        candidates = tuple(
            snapshot.items[index - 1] for index in selection.candidate_indices
        )
        allowed = tuple(
            source
            for source in snapshot.sources
            if source.item_index in selection.candidate_indices
        )
        if not allowed:
            raise ValueError("Research candidates have no reviewed source")
        choice_input = {
            "goal": context.conditions.goal,
            "budget_twd": str(context.conditions.budget_twd),
            "candidates": [
                {
                    "name": item.name,
                    "version": item.version_label,
                    "tags": item.flavor_tags,
                    "price_upper_twd": item.price_upper_bound_twd,
                }
                for item in candidates
            ],
            "provided_sources": [
                {
                    "index": source.index,
                    "item_name": snapshot.items[source.item_index - 1].name,
                    "publisher": source.publisher,
                }
                for source in allowed
            ],
        }
        chosen = await research_agent_v3().run(
            SOURCE_CHOICE_PROMPT_V3
            + f" 資料：{json.dumps(choice_input, ensure_ascii=False)}",
            usage_limits=UsageLimits(
                request_limit=2, total_tokens_limit=4000, output_tokens_limit=2000
            ),
        )
        source = next(
            (item for item in allowed if item.index == chosen.output.source_index),
            None,
        )
        if source is None:
            raise ValueError("INVALID_SOURCE_CHOICE")
        observation = await workflow.execute_activity(
            "whisky_read_source_v3",
            ReadSourceRequest(context, source),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
            result_type=SourceObservationReceipt,
        )
        selected_name = (
            next(
                (
                    item.name
                    for item in snapshot.items
                    if str(item.bottle_version_id) == answered[-1][1]
                ),
                None,
            )
            if answered
            else None
        )
        summary = _report_summary(candidates, selected_name)
        unresolved = _named_price_exclusions(context, snapshot)
        if observation.status != "ok":
            unresolved += (
                f"指定來源暫時無法讀取（{observation.code}）；仍以已覆核資料為準。",
            )
        if "不同桶型" in context.conditions.goal:
            unresolved += (
                "目前資料不足以確認候選與起點酒款的桶型差異；不將其視為已符合條件。",
            )
        report = ReportDraft(
            summary,
            tuple(
                ReportCandidate(
                    item.release_id,
                    item.item_id,
                    item.claims,
                    _render_reason(item, chosen.output.focus),
                    item.price_ids,
                )
                for item in candidates
            ),
            unresolved,
        )
        return ResearchDecision(report=report), _model_name(chosen), observation.id


def _version_choices(
    snapshot: ResearchCatalogSnapshot, indices: tuple[int, ...]
) -> tuple[UUID, ...]:
    return tuple(snapshot.items[index - 1].bottle_version_id for index in indices)


def _empty_budget_report(
    context: ResearchRunContext,
    snapshot: ResearchCatalogSnapshot,
    selection: ResearchSelection,
) -> ReportDraft:
    budget = context.conditions.budget_twd
    constraint = f"每瓶 TWD {budget} 預算" if budget is not None else "目前條件"
    return ReportDraft(
        f"本次已覆核酒款中，沒有同時符合{constraint}與要求的候選。",
        (),
        _named_price_exclusions(context, snapshot) + selection.unresolved,
    )


def _unlisted_report(name: str) -> ReportDraft:
    return ReportDraft(
        f"「{name}」不在本版已覆核酒款資料中，無法提供有來源的版本或風味比較。",
        (),
        ("可改從已收錄酒款或具體風味偏好繼續探索。",),
    )


def _named_price_exclusions(
    context: ResearchRunContext, snapshot: ResearchCatalogSnapshot
) -> tuple[str, ...]:
    notes = []
    for item in snapshot.items:
        if item.eligible or item.name not in context.conditions.goal:
            continue
        if item.price_upper_bound_twd is None:
            notes.append(
                f"{item.name} 目前沒有符合價格政策的台灣公開單瓶價，"
                "未列為嚴格預算候選。"
            )
        else:
            notes.append(
                f"{item.name} 的合格價格上緣為 TWD {item.price_upper_bound_twd}，"
                "超過本次預算。"
            )
    return tuple(notes)


def _report_summary(
    candidates: tuple[ResearchCatalogItem, ...], selected_name: str | None
) -> str:
    prefix = f"已確認起點版本為「{selected_name}」。" if selected_name else ""
    names = "、".join(f"「{item.name}」" for item in candidates)
    return f"{prefix}依目前已覆核資料，找到 {len(candidates)} 款可比較候選：{names}。"


def _render_reason(item: ResearchCatalogItem, focus: str) -> str:
    notes = item.tasting_notes.strip().rstrip("。；")
    if notes and not notes.startswith("品牌描述"):
        notes = "品牌描述：" + notes
    if not notes:
        notes = "品牌尚無可引用的風味描述"
    tags = (
        "；編輯整理的風味標籤：" + "、".join(item.flavor_tags)
        if item.flavor_tags
        else ""
    )
    if focus == "price" and item.price_upper_bound_twd is not None:
        return (
            f"合格台灣公開單瓶參考價上緣為 TWD {item.price_upper_bound_twd}；"
            f"{notes}{tags}。"
        )
    if focus == "version":
        return f"已覆核版本標示為「{item.version_label}」；{notes}{tags}。"
    return f"{notes}{tags}。"


def _model_name(result: object) -> str:
    messages = result.all_messages()  # type: ignore[attr-defined]
    response = next(
        message for message in reversed(messages) if isinstance(message, ModelResponse)
    )
    return response.model_name or "unknown-model"
