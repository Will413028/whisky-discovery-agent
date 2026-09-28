from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, update

from whisky.bootstrap.api import create_app
from whisky.bootstrap.migrate import upgrade
from whisky.modules.identity.public import IdentityAccess
from whisky.modules.identity.store import users
from whisky.modules.research.http import observation_router
from whisky.modules.research.observation import ObservationPolicy
from whisky.modules.research.views import TaskView


@pytest.fixture
def setup(postgres_url, signed_tokens):
    engine = create_engine(postgres_url)
    upgrade(engine, Path(__file__).parents[2] / "migrations")
    verifier, sign = signed_tokens
    access = IdentityAccess(engine, verifier)
    token = sign()
    owner = access.authenticate(token).actor_id
    run_id = uuid4()
    view = TaskView(
        task_id=uuid4(),
        thread_id=uuid4(),
        conditions_revision=1,
        view_version=1,
        status="researching",
        stage="合成 HTTP 觀察測試",
        question=None,
        report_id=None,
        error=None,
        observed_at="2026-09-28T00:00:00Z",
    )

    class Source:
        reads = 0

        async def read(self, request, actor_id):
            self.reads += 1
            if (
                actor_id == owner
                and request.task_id == view.task_id
                and request.run_id == run_id
            ):
                return view
            return None

    source = Source()
    app = create_app(
        observation_router=observation_router(
            access, source, ObservationPolicy(lifetime_seconds=0.08)
        )
    )
    payload = {
        "taskId": str(view.task_id),
        "runId": str(run_id),
        "conditionsRevision": 1,
    }
    try:
        yield app, access, token, sign, payload, source, engine, owner
    finally:
        engine.dispose()


@pytest.mark.integration
async def test_authenticated_observe_streams_snapshot_and_closes_without_completion(
    setup,
):
    app, _, token, _, payload, source, _, _ = setup
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/agent/observe", json=payload, headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "STATE_SNAPSHOT" in response.text
    assert "RUN_FINISHED" not in response.text
    assert source.reads == 1


async def test_product_app_mounts_observe_fail_closed_without_identity():
    async with AsyncClient(
        transport=ASGITransport(create_app()), base_url="http://test"
    ) as client:
        response = await client.post(
            "/agent/observe",
            json={
                "taskId": str(uuid4()),
                "runId": str(uuid4()),
                "conditionsRevision": 1,
            },
        )
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.integration
async def test_observe_rejects_missing_token_foreign_owner_and_command_payload(setup):
    app, _, token, sign, payload, source, _, _ = setup
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        missing = await client.post("/agent/observe", json=payload)
        foreign = await client.post(
            "/agent/observe",
            json=payload,
            headers={"Authorization": f"Bearer {sign(sub='auth0|other')}"},
        )
        command = await client.post(
            "/agent/observe",
            json=payload | {"answer": "start"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert missing.status_code == 401
    assert foreign.status_code == 404
    assert command.status_code == 422
    assert source.reads == 1


@pytest.mark.integration
async def test_stream_rechecks_actor_before_reading_another_snapshot(setup):
    import json

    from whisky.modules.research.http import AuthorizedSource
    from whisky.modules.research.observation import ObserveInput, Observer

    _, access, _, _, payload, source, engine, owner = setup
    now = [0.0]

    async def disable_actor(seconds):
        now[0] += seconds
        with engine.begin() as connection:
            connection.execute(
                update(users).where(users.c.id == owner).values(active=False)
            )

    stream = Observer(
        AuthorizedSource(access, source), sleep=disable_actor, clock=lambda: now[0]
    ).events(ObserveInput.model_validate(payload), owner)
    assert "RUN_STARTED" in await anext(stream)
    assert "STATE_SNAPSHOT" in await anext(stream)
    event = json.loads((await anext(stream)).removeprefix("data: ").strip())
    assert event["type"] == "RUN_ERROR"
    assert event["code"] == "OBSERVATION_ACCESS_LOST"
    assert source.reads == 1
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
