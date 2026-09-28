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
async def research_client(research_context, signed_tokens):
    engine, store, _, _ = research_context
    verifier, sign = signed_tokens
    identity = IdentityAccess(engine, verifier)
    token = sign()
    actor = identity.authenticate(token)
    plan = PlanStore(engine).create(
        actor.actor_id,
        actor.generation,
        "read-plan",
        ResearchConditions(entry="beginner", goal="探索果香"),
    )
    receipt = store.reserve(actor.actor_id, actor.generation, plan.id, 1, "start")
    app = create_app(
        observation_router=observation_router(
            identity, None, store=store, reports=ReportStore(engine)
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        yield client, sign, engine, store, actor, receipt


async def test_task_and_command_recover_pending_then_accepted(research_client):
    client, sign, _, store, actor, receipt = research_client
    headers = {"Authorization": f"Bearer {sign()}"}
    for acceptance, status in [
        ("acceptance_pending", "acceptance_pending"),
        ("accepted", "queued"),
    ]:
        command = await client.get(f"/api/v1/commands/{receipt.id}", headers=headers)
        task = await client.get(f"/api/v1/tasks/{receipt.task_id}", headers=headers)
        assert command.status_code == task.status_code == 200
        assert (
            command.headers["cache-control"]
            == task.headers["cache-control"]
            == "no-store"
        )
        assert command.json() == {
            "id": str(receipt.id),
            "taskId": str(receipt.task_id),
            "scope": "research.start",
            "acceptance": acceptance,
        }
        assert task.json()["status"] == status
        assert task.json()["taskId"] == str(receipt.task_id)
        assert "ownerId" not in task.json() and "workflowId" not in task.json()
        store.confirm(actor.actor_id, actor.generation, receipt.id, "test-runtime-run")


async def test_saved_report_exposes_immutable_claims_prices_and_owner_boundary(
    research_client,
):
    client, sign, engine, store, actor, receipt = research_client
    release = synthetic_release()
    CatalogStore(engine).publish(release)
    store.confirm(actor.actor_id, actor.generation, receipt.id, "test-runtime-run")
    item = release.items[0]
    fact = item.facts[0]
    saved = ReportStore(engine).save(
        actor.actor_id,
        actor.generation,
        receipt.task_id,
        "http-report-v1",
        ReportDraft(
            summary="來源可查",
            candidates=(
                ReportCandidate(
                    release.id,
                    item.id,
                    (ReportClaim("fact", fact.field, fact.value, fact.evidence_ids),),
                    "依官方描述探索",
                ),
            ),
        ),
        policy_version="price-30d-v1",
        prompt_version="research-v1",
        model_version="fixture-v1",
    )
    path = f"/api/v1/reports/{saved.id}"
    own = await client.get(path, headers={"Authorization": f"Bearer {sign()}"})
    assert own.status_code == 200
    body = own.json()
    assert body["id"] == str(saved.id)
    assert body["catalogReleaseId"] == str(release.id)
    assert body["candidates"][0]["claims"][0]["value"] == fact.value
    assert body["candidates"][0]["claims"][0]["sources"][0]["url"]
    assert body["candidates"][0]["prices"] == []
    assert body["policyVersion"] == "price-30d-v1"
    assert own.headers["cache-control"] == "no-store"
    foreign = await client.get(
        path, headers={"Authorization": f"Bearer {sign(sub='foreign')}"}
    )
    assert foreign.status_code == 404
    assert (await client.get(path)).status_code == 401


@pytest.mark.parametrize("resource", ["tasks", "commands"])
async def test_research_reads_authenticate_and_hide_foreign_resources(
    research_client, resource
):
    client, sign, _, _, _, receipt = research_client
    identifier = receipt.task_id if resource == "tasks" else receipt.id
    path = f"/api/v1/{resource}/{identifier}"
    assert (await client.get(path)).status_code == 401
    headers = {"Authorization": f"Bearer {sign(sub='foreign')}"}
    foreign = await client.get(path, headers=headers)
    missing = await client.get(f"/api/v1/{resource}/{uuid4()}", headers=headers)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["code"] == missing.json()["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "change,status", [("generation = generation + 1", 404), ("active = false", 403)]
)
async def test_research_reads_hide_previous_identity_generation(
    research_client, change, status
):
    client, sign, engine, _, actor, receipt = research_client
    with engine.begin() as connection:
        connection.execute(
            text(f"UPDATE users SET {change} WHERE id = :id"), {"id": actor.actor_id}
        )
    for resource, identifier in [("tasks", receipt.task_id), ("commands", receipt.id)]:
        response = await client.get(
            f"/api/v1/{resource}/{identifier}",
            headers={"Authorization": f"Bearer {sign()}"},
        )
        assert response.status_code == status


@pytest.mark.parametrize("lose_response", [False, True])
async def test_http_recovers_actual_temporal_acceptance(research_client, lose_response):
    from temporalio.client import Client
    from temporalio.testing import WorkflowEnvironment
    from test_research_start import LoseFirstResponse

    from whisky.modules.research.acceptance import AcceptResearch
    from whisky.modules.research.temporal_start import TemporalResearchStarter

    client, sign, engine, store, actor, _ = research_client
    plan = PlanStore(engine).create(
        actor.actor_id,
        actor.generation,
        "temporal-read-plan",
        ResearchConditions(entry="beginner", goal="真服務接受後恢復"),
    )
    headers = {"Authorization": f"Bearer {sign()}"}
    async with await WorkflowEnvironment.start_local() as env:
        temporal = (
            Client(**{**env.client.config(), "interceptors": [LoseFirstResponse()]})
            if lose_response
            else env.client
        )
        service = AcceptResearch(
            store, TemporalResearchStarter(temporal, f"test-{uuid4()}")
        )
        first = await service.execute(
            actor.actor_id, actor.generation, plan.id, 1, "http-recovery"
        )
        original = await env.client.get_workflow_handle(first.workflow_id).describe()
        pending = await client.get(f"/api/v1/commands/{first.id}", headers=headers)
        assert pending.json()["acceptance"] == (
            "acceptance_pending" if lose_response else "accepted"
        )
        recovered = await service.execute(
            actor.actor_id, actor.generation, plan.id, 1, "http-recovery"
        )
        assert recovered.id == first.id and recovered.task_id == first.task_id
        assert (
            await env.client.get_workflow_handle(first.workflow_id).describe()
        ).run_id == original.run_id
        command = await client.get(f"/api/v1/commands/{first.id}", headers=headers)
        task = await client.get(f"/api/v1/tasks/{first.task_id}", headers=headers)
        assert command.json()["acceptance"] == "accepted"
        assert task.json()["status"] == "queued"
