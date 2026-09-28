"""Read-only observation of an existing task; never executes research."""

import asyncio
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from ag_ui.core import (
    CustomEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunFinishedSuccessOutcome,
    RunStartedEvent,
    StateSnapshotEvent,
)
from ag_ui.encoder import EventEncoder
from fastapi import HTTPException
from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from whisky.modules.research.public import waiting_event
from whisky.modules.research.views import QuestionView, ReportView, TaskView, ViewModel


class ObserveInput(ViewModel):
    task_id: UUID
    run_id: UUID
    conditions_revision: int = Field(ge=1)


class ObservationSource(Protocol):
    async def read(self, request: ObserveInput, owner: UUID) -> TaskView | None: ...

    async def outcome(self, request: ObserveInput, owner: UUID) -> dict | None: ...

    async def report(self, report_id: UUID, owner: UUID) -> ReportView | None: ...


@dataclass(frozen=True)
class ObservationPolicy:
    poll_seconds: float = 2
    heartbeat_seconds: float = 15
    lifetime_seconds: float = 60
    connections_per_owner: int = 2


class BoundedStream(StreamingResponse):
    def __init__(
        self,
        content: AsyncGenerator[str],
        timeout: float,
        release: Callable[[], None],
    ) -> None:
        super().__init__(
            content,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store"},
        )
        self.timeout = timeout
        self.release = release
        self.content = content

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        deadline = time.monotonic() + self.timeout
        try:
            # Reserve a bounded closing window inside the total connection deadline.
            async with asyncio.timeout(max(0, self.timeout - 0.01)):
                await super().__call__(scope, receive, send)
        except TimeoutError:
            try:
                async with asyncio.timeout(max(0, deadline - time.monotonic())):
                    await send(
                        {"type": "http.response.body", "body": b"", "more_body": False}
                    )
            except TimeoutError:
                pass
        finally:
            try:
                await self.content.aclose()
            finally:
                self.release()


class Observer:
    def __init__(
        self,
        source: ObservationSource,
        policy: ObservationPolicy = ObservationPolicy(),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.source = source
        self.policy = policy
        self.sleep = sleep
        self.clock = clock
        self.connections: dict[UUID, int] = {}

    async def response(
        self, request: ObserveInput, owner: UUID, expires_at: float
    ) -> StreamingResponse:
        timeout = min(expires_at - time.time(), self.policy.lifetime_seconds)
        if timeout <= 0:
            raise HTTPException(401, "UNAUTHENTICATED")
        count = self.connections.get(owner, 0)
        if count >= self.policy.connections_per_owner:
            raise HTTPException(429, "OBSERVATION_LIMIT", headers={"Retry-After": "2"})
        self.connections[owner] = count + 1

        def release() -> None:
            remaining = self.connections[owner] - 1
            if remaining:
                self.connections[owner] = remaining
            else:
                del self.connections[owner]

        stream = self.events(request, owner)
        started = time.monotonic()
        try:
            async with asyncio.timeout(timeout):
                first = await anext(stream)
        except BaseException as error:
            await stream.aclose()
            release()
            if isinstance(error, LookupError):
                raise HTTPException(404, "NOT_FOUND") from None
            if isinstance(error, TimeoutError):
                raise HTTPException(503, "OBSERVATION_UNAVAILABLE") from None
            raise

        async def content() -> AsyncGenerator[str]:
            try:
                yield first
                async for frame in stream:
                    yield frame
            finally:
                await stream.aclose()

        return BoundedStream(
            content(), max(0, timeout - (time.monotonic() - started)), release
        )

    async def events(self, request: ObserveInput, owner: UUID) -> AsyncGenerator[str]:
        view = await self.source.read(request, owner)
        if (
            view is None
            or view.task_id != request.task_id
            or view.conditions_revision != request.conditions_revision
        ):
            raise LookupError("Observation is unavailable")
        encoder = EventEncoder()
        yield encoder.encode(
            RunStartedEvent(thread_id=str(view.thread_id), run_id=str(request.run_id))
        )
        yield encoder.encode(
            StateSnapshotEvent(snapshot=view.model_dump(mode="json", by_alias=True))
        )
        outcome = await self.source.outcome(request, owner)
        if outcome is not None and outcome.get("type") == "interrupt":
            yield self.interrupt_frame(outcome, view, request, encoder)
            return
        if view.status in {"completed", "failed", "cancelled", "superseded"}:
            async for frame in self.terminal_events(view, request, owner, encoder):
                yield frame
            return
        thread_id = view.thread_id
        version = view.view_version
        next_poll = self.clock() + self.policy.poll_seconds
        next_heartbeat = self.clock() + self.policy.heartbeat_seconds
        while True:
            await self.sleep(max(0, min(next_poll, next_heartbeat) - self.clock()))
            now = self.clock()
            if now >= next_heartbeat:
                next_heartbeat = now + self.policy.heartbeat_seconds
                yield ": heartbeat\n\n"
            if now < next_poll:
                continue
            next_poll = now + self.policy.poll_seconds
            try:
                view = await self.source.read(request, owner)
                outcome = await self.source.outcome(request, owner)
            except SQLAlchemyError:
                yield encoder.encode(
                    RunErrorEvent(
                        code="OBSERVATION_UNAVAILABLE",
                        message="觀察暫時中斷，請重新連線。",
                    )
                )
                return
            if (
                view is None
                or view.task_id != request.task_id
                or view.conditions_revision != request.conditions_revision
                or view.thread_id != thread_id
            ):
                yield encoder.encode(
                    RunErrorEvent(
                        code="OBSERVATION_ACCESS_LOST",
                        message="無法繼續觀察此工作。",
                    )
                )
                return
            if view.view_version > version:
                version = view.view_version
                yield encoder.encode(
                    StateSnapshotEvent(
                        snapshot=view.model_dump(mode="json", by_alias=True)
                    )
                )
            if outcome is not None and outcome.get("type") == "interrupt":
                yield self.interrupt_frame(outcome, view, request, encoder)
                return
            if view.status in {"completed", "failed", "cancelled", "superseded"}:
                async for frame in self.terminal_events(view, request, owner, encoder):
                    yield frame
                return

    @staticmethod
    def interrupt_frame(
        outcome: dict,
        view: TaskView,
        request: ObserveInput,
        encoder: EventEncoder,
    ) -> str:
        try:
            question = QuestionView.model_validate(outcome["question"])
        except (KeyError, ValueError):
            return encoder.encode(
                RunErrorEvent(
                    code="RUN_OUTCOME_UNAVAILABLE",
                    message="暫時無法讀取補充問題，請重新連線。",
                )
            )
        return encoder.encode(
            waiting_event(
                str(view.thread_id),
                str(request.run_id),
                str(question.id),
                prompt=question.prompt,
                choices=question.choices,
                expires_at=question.expires_at.isoformat(),
            )
        )

    async def terminal_events(
        self,
        view: TaskView,
        request: ObserveInput,
        owner: UUID,
        encoder: EventEncoder,
    ) -> AsyncGenerator[str]:
        if view.status == "completed" and view.report_id is not None:
            try:
                report = await self.source.report(view.report_id, owner)
            except SQLAlchemyError:
                report = None
            if report is None:
                yield encoder.encode(
                    RunErrorEvent(
                        code="REPORT_UNAVAILABLE",
                        message="暫時無法讀取已保存的報告，請重新連線。",
                    )
                )
                return
            yield encoder.encode(
                CustomEvent(
                    name="whisky.report",
                    value=report.model_dump(mode="json", by_alias=True),
                )
            )
            yield encoder.encode(
                RunFinishedEvent(
                    thread_id=str(view.thread_id),
                    run_id=str(request.run_id),
                    outcome=RunFinishedSuccessOutcome(),
                )
            )
        elif view.status in {"failed", "cancelled", "superseded"}:
            codes = {
                "cancelled": ("TASK_CANCELLED", "研究已取消。"),
                "superseded": ("TASK_SUPERSEDED", "研究條件已更新。"),
            }
            code, message = codes.get(
                view.status,
                (
                    view.error.code if view.error else "RESEARCH_FAILED",
                    view.error.message if view.error else "研究未完成。",
                ),
            )
            yield encoder.encode(RunErrorEvent(code=code, message=message))
