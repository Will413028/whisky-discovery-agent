import asyncio
import json
import time
from uuid import uuid4

import pytest
from fastapi import HTTPException

from whisky.modules.research.observation import (
    ObservationPolicy,
    ObserveInput,
    Observer,
)
from whisky.modules.research.views import TaskView


def task(**changes):
    return TaskView.model_validate(
        dict(
            taskId="00000000-0000-4000-8000-000000000001",
            threadId="00000000-0000-4000-8000-000000000002",
            conditionsRevision=1,
            viewVersion=1,
            status="researching",
            stage="合成觀察測試",
            question=None,
            reportId=None,
            error=None,
            observedAt="2026-09-28T00:00:00Z",
        )
        | changes
    )


class Source:
    def __init__(self, view, owner):
        self.view = view
        self.owner = owner
        self.reads = []

    async def read(self, request, owner):
        self.reads.append((request, owner))
        return self.view if owner == self.owner else None


def request_for(view):
    return ObserveInput(task_id=view.task_id, run_id=uuid4(), conditions_revision=1)


async def test_observe_existing_task_emits_run_and_authoritative_snapshot():
    owner = uuid4()
    view = task()
    source = Source(view, owner)
    request = request_for(view)
    events = Observer(source).events(request, owner)
    found = []
    async for frame in events:
        found.append(json.loads(frame.removeprefix("data: ").strip()))
        if len(found) == 2:
            break
    await events.aclose()
    assert [event["type"] for event in found] == ["RUN_STARTED", "STATE_SNAPSHOT"]
    assert found[0]["runId"] == str(request.run_id)
    assert found[1]["snapshot"] == view.model_dump(mode="json", by_alias=True)
    assert source.reads == [(request, owner)]


@pytest.mark.parametrize(
    "changes",
    [
        {"taskId": str(uuid4())},
        {"conditionsRevision": 2},
    ],
)
async def test_observe_rejects_wrong_task_or_revision(changes):
    owner = uuid4()
    request = request_for(task())
    source = Source(task(**changes), owner)
    with pytest.raises(LookupError):
        await anext(Observer(source).events(request, owner))


async def test_other_owner_cannot_observe():
    source = Source(task(), uuid4())
    with pytest.raises(LookupError):
        await anext(Observer(source).events(request_for(task()), uuid4()))


async def test_poll_rechecks_owner_and_emits_only_newer_versions():
    owner = uuid4()
    source = Source(task(viewVersion=2), owner)
    versions = iter([2, 1, 3, None])
    waits = []
    now = [0.0]

    async def tick(seconds):
        waits.append(seconds)
        now[0] += seconds
        version = next(versions)
        source.view = task(viewVersion=version) if version else None

    found = []
    async for frame in Observer(source, sleep=tick, clock=lambda: now[0]).events(
        request_for(task()), owner
    ):
        event = json.loads(frame.removeprefix("data: ").strip())
        if event["type"] == "STATE_SNAPSHOT":
            found.append(event["snapshot"]["viewVersion"])
    assert event["type"] == "RUN_ERROR"
    assert event["code"] == "OBSERVATION_ACCESS_LOST"
    assert found == [2, 3]
    assert waits == [2, 2, 2, 2]
    assert all(read_owner == owner for _, read_owner in source.reads)


async def test_heartbeat_without_new_snapshot_does_not_complete_task():
    owner = uuid4()
    source = Source(task(), owner)
    now = [0.0]

    async def tick(seconds):
        now[0] += seconds
        assert now[0] <= 15, "heartbeat must arrive at its configured deadline"

    events = Observer(source, sleep=tick, clock=lambda: now[0]).events(
        request_for(task()), owner
    )
    await anext(events)
    await anext(events)
    assert await anext(events) == ": heartbeat\n\n"
    assert now[0] == 15
    await events.aclose()


async def run_response(response, send):
    async def receive():
        await asyncio.Event().wait()

    await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)


async def test_two_slots_per_owner_released_even_when_consumer_stalls():
    owner = uuid4()
    observer = Observer(Source(task(), owner), ObservationPolicy(lifetime_seconds=0.03))
    request = request_for(task())
    first = await observer.response(request, owner, time.time() + 60)
    second = await observer.response(request, owner, time.time() + 60)
    with pytest.raises(HTTPException) as error:
        await observer.response(request, owner, time.time() + 60)
    assert error.value.status_code == 429
    started = asyncio.Event()

    async def stalled_send(_message):
        started.set()
        await asyncio.Event().wait()

    running = asyncio.create_task(run_response(first, stalled_send))
    await asyncio.wait_for(started.wait(), 1)
    await asyncio.wait_for(running, 1)
    replacement = await observer.response(request, owner, time.time() + 60)
    await asyncio.gather(
        run_response(second, stalled_send), run_response(replacement, stalled_send)
    )


async def test_expired_token_rejected_before_stream_and_slot_reservation():
    owner = uuid4()
    observer = Observer(Source(task(), owner))
    for _ in range(3):
        with pytest.raises(HTTPException) as error:
            await observer.response(request_for(task()), owner, time.time() - 1)
        assert error.value.status_code == 401


async def test_missing_task_rejected_before_http_headers_and_releases_slot():
    owner = uuid4()
    observer = Observer(Source(None, owner))
    for _ in range(3):
        with pytest.raises(HTTPException) as error:
            await observer.response(request_for(task()), owner, time.time() + 60)
        assert error.value.status_code == 404
    assert observer.connections == {}


async def test_disconnect_releases_slot_and_token_expiry_bounds_stalled_send():
    owner = uuid4()
    observer = Observer(Source(task(), owner))
    response = await observer.response(request_for(task()), owner, time.time() + 0.03)
    started = asyncio.Event()

    async def stalled_send(_message):
        started.set()
        await asyncio.Event().wait()

    pending = asyncio.create_task(run_response(response, stalled_send))
    await asyncio.wait_for(started.wait(), 1)
    await asyncio.wait_for(pending, 1)
    assert observer.connections == {}
    response = await observer.response(request_for(task()), owner, time.time() + 60)
    started.clear()
    pending = asyncio.create_task(run_response(response, stalled_send))
    await asyncio.wait_for(started.wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert observer.connections == {}


async def test_poll_failure_emits_safe_transport_error_without_task_completion():
    from sqlalchemy.exc import OperationalError

    owner = uuid4()

    class BrokenSource(Source):
        async def read(self, request, actor_id):
            if self.reads:
                raise OperationalError(
                    "private SQL", {}, Exception("secret database URL")
                )
            return await super().read(request, actor_id)

    source = BrokenSource(task(), owner)
    events = Observer(source, ObservationPolicy(poll_seconds=0.001)).events(
        request_for(task()), owner
    )
    await anext(events)
    await anext(events)
    frame = await asyncio.wait_for(anext(events), 1)
    event = json.loads(frame.removeprefix("data: ").strip())
    assert event == {
        "type": "RUN_ERROR",
        "code": "OBSERVATION_UNAVAILABLE",
        "message": "觀察暫時中斷，請重新連線。",
    }
    assert "secret" not in frame
    with pytest.raises(StopAsyncIteration):
        await anext(events)
