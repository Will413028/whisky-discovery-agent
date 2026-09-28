from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from whisky.bootstrap.api import create_app
from whisky.modules.discovery.http import plan_router
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.public import IdentityAccess

pytestmark = pytest.mark.integration


@pytest.fixture
async def plan_client(research_context, signed_tokens):
    engine, _, _, _ = research_context
    verifier, sign = signed_tokens
    app = create_app(
        plan_router=plan_router(IdentityAccess(engine, verifier), PlanStore(engine))
    )
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        yield client, sign


def command(**changes):
    return {
        "key": "create-1",
        "conditions": {"entry": "beginner", "goal": "探索果香"},
        **changes,
    }


async def test_create_and_restore_plan_with_verified_actor(plan_client):
    client, sign = plan_client
    headers = {"Authorization": f"Bearer {sign()}"}
    response = await client.post("/api/v1/plans", headers=headers, json=command())
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["conditionsRevision"] == 1
    assert body["conditions"]["goal"] == "探索果香"
    again = await client.post("/api/v1/plans", headers=headers, json=command())
    assert again.status_code == 201 and again.json() == body
    restored = await client.get(f"/api/v1/plans/{body['id']}", headers=headers)
    assert restored.status_code == 200 and restored.json() == body


async def test_create_plan_requires_authentication(plan_client):
    client, _ = plan_client
    response = await client.post("/api/v1/plans", json=command())
    assert response.status_code == 401


async def test_plan_conflict_is_typed_and_safe(plan_client):
    client, sign = plan_client
    headers = {"Authorization": f"Bearer {sign()}"}
    await client.post("/api/v1/plans", headers=headers, json=command())
    response = await client.post(
        "/api/v1/plans",
        headers=headers,
        json=command(conditions={"entry": "beginner", "goal": "探索香草"}),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert response.json()["retryable"] is False
    assert response.json()["request_id"]


async def test_plan_cross_actor_matches_missing(plan_client):
    client, sign = plan_client
    own = {"Authorization": f"Bearer {sign()}"}
    other = {"Authorization": f"Bearer {sign(sub='second-actor')}"}
    created = await client.post("/api/v1/plans", headers=own, json=command())
    assert created.status_code == 201
    foreign = await client.get(f"/api/v1/plans/{created.json()['id']}", headers=other)
    missing = await client.get(f"/api/v1/plans/{uuid4()}", headers=other)
    assert foreign.status_code == missing.status_code == 404
    one, two = foreign.json(), missing.json()
    one.pop("request_id")
    two.pop("request_id")
    assert one == two


@pytest.mark.parametrize(
    "changes",
    [
        {"owner": str(uuid4())},
        {"key": " "},
        {"key": "x" * 129},
        {"conditions": {"entry": "beginner", "goal": "", "owner_id": str(uuid4())}},
    ],
)
async def test_invalid_plan_command_is_rejected(plan_client, changes):
    client, sign = plan_client
    response = await client.post(
        "/api/v1/plans",
        json=command(**changes),
        headers={"Authorization": f"Bearer {sign()}"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"


async def test_plan_list_has_bounded_resumable_pages(plan_client):
    client, sign = plan_client
    headers = {"Authorization": f"Bearer {sign()}"}
    ids = set()
    for i in range(3):
        response = await client.post(
            "/api/v1/plans", headers=headers, json=command(key=f"page-{i}")
        )
        ids.add(response.json()["id"])
    first = await client.get("/api/v1/plans?limit=2", headers=headers)
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert len(first.json()["items"]) == 2
    cursor = first.json()["nextCursor"]
    assert cursor
    last = await client.get(
        "/api/v1/plans", params={"limit": 2, "cursor": cursor}, headers=headers
    )
    assert last.status_code == 200
    assert len(last.json()["items"]) == 1 and last.json()["nextCursor"] is None
    assert {item["id"] for item in first.json()["items"] + last.json()["items"]} == ids
    foreign = await client.get(
        "/api/v1/plans",
        params={"cursor": cursor},
        headers={"Authorization": f"Bearer {sign(sub='another')}"},
    )
    assert foreign.status_code == 200 and foreign.json()["items"] == []


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=51",
        "limit=abc",
        "other=1",
        "cursor=bad!",
        "cursor=",
        "limit=1&limit=2",
        "cursor=x&cursor=y",
    ],
)
async def test_invalid_plan_pagination_is_rejected(plan_client, query):
    client, sign = plan_client
    response = await client.get(
        f"/api/v1/plans?{query}", headers={"Authorization": f"Bearer {sign()}"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"


async def test_plan_list_requires_authentication(plan_client):
    client, _ = plan_client
    response = await client.get("/api/v1/plans")
    assert response.status_code == 401
