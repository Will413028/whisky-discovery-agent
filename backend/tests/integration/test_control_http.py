"""Control HTTP exposes pending, proposed, and completed receipts safely."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from whisky.bootstrap.api import create_app
from whisky.modules.control.activities import ControlActivities
from whisky.modules.control.http import control_router
from whisky.modules.control.journal import MemoryControlJournal
from whisky.modules.control.service import ControlController
from whisky.modules.control.store import ControlStore
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.public import IdentityAccess
from whisky.modules.identity.public import router as identity_router

pytestmark = pytest.mark.integration


class AcceptedOnlyStarter:
    async def start(self, receipt):
        return str(uuid4())


async def test_cancel_http_reconciles_original_command_after_lost_response(
    research_context, signed_tokens
):
    engine, research, _, _ = research_context
    verifier, sign = signed_tokens
    token = sign(sub="auth0|control-http")
    access = IdentityAccess(engine, verifier)
    session = access.authenticate(token)
    plan = PlanStore(engine).create(
        session.actor_id,
        session.generation,
        "control-plan",
        ResearchConditions(entry="beginner", goal="探索果香"),
    )
    started = research.reserve(
        session.actor_id, session.generation, plan.id, 1, "control-start"
    )
    store = ControlStore(engine)
    activities = ControlActivities(store, MemoryControlJournal())
    app = create_app(
        identity_router=identity_router(engine, verifier),
        control_router=control_router(
            access, store, ControlController(store, AcceptedOnlyStarter())
        ),
    )
    headers = {"Authorization": f"Bearer {token}"}
    path = f"/api/v1/tasks/{started.task_id}/cancel"
    cancel_key = str(uuid4())
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        proposed = await client.post(path, headers=headers, json={"key": cancel_key})
        assert proposed.status_code == 202
        assert proposed.json()["status"] == "pending"
        command_id = proposed.json()["id"]
        assert proposed.headers["cache-control"] == "no-store"
        await activities.persist_intent(command_id)
        offered = await client.get(
            f"/api/v1/control-commands/{command_id}", headers=headers
        )
        assert offered.status_code == 200
        assert offered.json()["status"] == "intent_confirmed"
        await activities.apply_effect(command_id)
        await activities.persist_result(command_id)
        replay = await client.post(path, headers=headers, json={"key": cancel_key})
        assert replay.status_code == 200
        assert replay.json()["id"] == command_id
        assert replay.json()["status"] == "completed"
        access.authenticate(sign(sub="auth0|other"))
        foreign = await client.get(
            f"/api/v1/control-commands/{command_id}",
            headers={"Authorization": f"Bearer {sign(sub='auth0|other')}"},
        )
        assert foreign.status_code == 404


async def test_deleted_actor_can_reconcile_only_its_delete_command(
    research_context, signed_tokens
):
    engine, _, _, _ = research_context
    verifier, sign = signed_tokens
    token = sign(sub="auth0|delete-actor")
    access = IdentityAccess(engine, verifier)
    session = access.authenticate(token)
    store = ControlStore(engine)
    old_plan = PlanStore(engine).create(
        session.actor_id,
        session.generation,
        "old-control-plan",
        ResearchConditions(entry="beginner", goal="待刪除"),
    )
    old_command = store.reserve(
        session.actor_id, session.generation, "plan.delete", old_plan.id, str(uuid4())
    )
    activities = ControlActivities(store, MemoryControlJournal())
    app = create_app(
        identity_router=identity_router(engine, verifier),
        control_router=control_router(
            access, store, ControlController(store, AcceptedOnlyStarter())
        ),
    )
    headers = {"Authorization": f"Bearer {token}"}
    delete_key = str(uuid4())
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/v1/me/delete", headers=headers, json={"key": delete_key}
        )
        assert first.status_code == 202
        command_id = first.json()["id"]
        await activities.persist_intent(command_id)
        await activities.apply_effect(command_id)
        await activities.persist_result(command_id)
        recovered = await client.get(
            f"/api/v1/control-commands/{command_id}", headers=headers
        )
        assert recovered.status_code == 200
        assert recovered.json()["status"] == "completed"
        assert (
            await client.get(
                f"/api/v1/control-commands/{old_command.id}", headers=headers
            )
        ).status_code == 404
        again = await client.post(
            "/api/v1/me/delete", headers=headers, json={"key": delete_key}
        )
        assert again.status_code == 200
        assert again.json()["id"] == command_id
        assert (await client.get("/api/v1/me", headers=headers)).status_code == 403
        assert (
            await client.post(
                "/api/v1/me/delete", headers=headers, json={"key": str(uuid4())}
            )
        ).status_code == 403
