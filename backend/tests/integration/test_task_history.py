"""Plan history uses immutable task revisions, not the current plan snapshot."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from test_catalog_release import synthetic_release

from whisky.bootstrap.api import create_app
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.public import IdentityAccess
from whisky.modules.research.http import observation_router
from whisky.modules.research.report import ReportCandidate, ReportClaim, ReportDraft
from whisky.modules.research.report_store import ReportStore

pytestmark = pytest.mark.integration


@pytest.fixture
async def history_client(research_context, signed_tokens):
    engine, store, _, _ = research_context
    verifier, sign = signed_tokens
    identity = IdentityAccess(engine, verifier)
    actor = identity.authenticate(sign())
    plan = PlanStore(engine).create(
        actor.actor_id,
        actor.generation,
        "history-plan",
        ResearchConditions(entry="beginner", goal="探索果香"),
    )
    old = store.reserve(actor.actor_id, actor.generation, plan.id, 1, "history-old")
    store.confirm(actor.actor_id, actor.generation, old.id, "history-run")
    release = synthetic_release()
    CatalogStore(engine).publish(release)
    item = release.items[0]
    fact = item.facts[0]
    reports = ReportStore(engine)
    saved = reports.save(
        actor.actor_id,
        actor.generation,
        old.task_id,
        "history-report",
        ReportDraft(
            summary="合成測試來源",
            candidates=(
                ReportCandidate(
                    release.id,
                    item.id,
                    (ReportClaim("fact", fact.field, fact.value, fact.evidence_ids),),
                    "合成測試候選",
                ),
            ),
        ),
        policy_version="price-30d-v1",
        prompt_version="research-v1",
        model_version="fixture-v1",
    )
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE plans SET conditions_revision=2 WHERE id=:id"), {"id": plan.id}
        )
    current = store.reserve(
        actor.actor_id, actor.generation, plan.id, 2, "history-current"
    )
    # A tie must be ordered by UUID; observedAt is deliberately unrelated.
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE research_tasks SET created_at='2026-09-29T00:00:00Z' "
                "WHERE plan_id=:id"
            ),
            {"id": plan.id},
        )
    app = create_app(
        observation_router=observation_router(
            identity, None, store=store, reports=reports
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        yield client, sign, engine, actor, plan, old, current, saved


async def test_history_preserves_completed_report_and_revision_with_keyset(
    history_client,
):
    client, sign, _, _, plan, old, current, saved = history_client
    headers = {"Authorization": f"Bearer {sign()}"}
    path = f"/api/v1/plans/{plan.id}/tasks"
    first = await client.get(path, params={"limit": 1}, headers=headers)
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    page = first.json()
    assert len(page["items"]) == 1 and page["nextCursor"]
    second = await client.get(
        path, params={"limit": 1, "cursor": page["nextCursor"]}, headers=headers
    )
    assert second.status_code == 200
    assert second.json()["nextCursor"] is None
    items = page["items"] + second.json()["items"]
    assert [row["task"]["taskId"] for row in items] == sorted(
        [str(old.task_id), str(current.task_id)], reverse=True
    )
    historical = next(row for row in items if row["task"]["taskId"] == str(old.task_id))
    assert historical["task"]["conditionsRevision"] == 1
    assert historical["task"]["reportId"] == str(saved.id)
    assert historical["task"]["status"] == "completed"
    assert historical["createdAt"] == "2026-09-29T00:00:00Z"
    assert (await client.get(f"/api/v1/reports/{saved.id}", headers=headers)).json()[
        "summary"
    ] == "合成測試來源"


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=51",
        "cursor=invalid",
        "limit=1&limit=2",
        "cursor=x&cursor=y",
        "unknown=1",
    ],
)
async def test_history_rejects_invalid_pagination(history_client, query):
    client, sign, _, _, plan, *_ = history_client
    response = await client.get(
        f"/api/v1/plans/{plan.id}/tasks?{query}",
        headers={"Authorization": f"Bearer {sign()}"},
    )
    assert response.status_code == 422


async def test_history_hides_foreign_missing_and_deleted_plans(history_client):
    client, sign, engine, _, plan, *_ = history_client
    path = f"/api/v1/plans/{plan.id}/tasks"
    own = {"Authorization": f"Bearer {sign()}"}
    assert (await client.get(path)).status_code == 401
    assert (
        await client.get(
            path, headers={"Authorization": f"Bearer {sign(sub='foreign')}"}
        )
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/plans/{uuid4()}/tasks", headers=own)
    ).status_code == 404
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE plans SET deleted_at=now() WHERE id=:id"), {"id": plan.id}
        )
    assert (await client.get(path, headers=own)).status_code == 404
