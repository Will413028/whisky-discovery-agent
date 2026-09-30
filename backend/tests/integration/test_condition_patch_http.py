"""Partial edits replay one durable full-snapshot command, not a fresh DB read."""

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from test_control_recovery import PagedJournal

from whisky.bootstrap.api import create_app
from whisky.modules.control.activities import ControlActivities
from whisky.modules.control.http import control_router
from whisky.modules.control.recovery import reconcile_control_log
from whisky.modules.control.service import ControlController
from whisky.modules.control.store import ControlStore
from whisky.modules.discovery.conditions import Preference, ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.public import IdentityAccess

pytestmark = pytest.mark.integration


class AcceptedOnlyStarter:
    async def start(self, receipt):
        return str(uuid4())


@pytest.fixture
def patch_context(research_context, signed_tokens):
    engine, _, _, _ = research_context
    verifier, sign = signed_tokens
    token = sign(sub="auth0|patch-http")
    identity = IdentityAccess(engine, verifier)
    actor = identity.authenticate(token)
    plan = PlanStore(engine).create(
        actor.actor_id,
        actor.generation,
        "partial edit",
        ResearchConditions(
            entry="beginner",
            goal="保留果香，探索下一款",
            budget_twd=Decimal("1000"),
            preferences=(
                Preference(
                    description="果香",
                    intent="keep",
                    certainty="user_stated",
                    strength="soft",
                ),
            ),
        ),
    )
    store = ControlStore(engine)
    journal = PagedJournal(page_size=1)
    app = create_app(
        control_router=control_router(
            identity, store, ControlController(store, AcceptedOnlyStarter())
        )
    )
    body = {
        "key": str(uuid4()),
        "expectedRevision": 1,
        "baseConditions": plan.conditions.model_dump(mode="json"),
        "patch": {"budget_twd": "900"},
    }
    return (
        engine,
        actor,
        plan,
        ControlActivities(store, journal),
        app,
        {"Authorization": f"Bearer {token}"},
        body,
    )


async def test_patch_preserves_fields_and_replays_after_revision_changes(patch_context):
    engine, actor, plan, activities, app, headers, body = patch_context
    path = f"/api/v1/plans/{plan.id}/conditions/patch"
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        first = await client.post(path, headers=headers, json=body)
        assert first.status_code == 202
        command_id = first.json()["id"]
        assert first.headers["cache-control"] == "no-store"
        await activities.persist_intent(command_id)
        await activities.apply_effect(command_id)
        await activities.persist_result(command_id)
        current = PlanStore(engine).read(plan.id, actor.actor_id)
        assert current.conditions_revision == 2
        assert current.conditions.budget_twd == Decimal("900")
        assert current.conditions.model_dump(
            exclude={"budget_twd"}
        ) == plan.conditions.model_dump(exclude={"budget_twd"})
        replay = await client.post(path, headers=headers, json=body)
        assert replay.status_code == 200
        assert replay.json()["id"] == command_id
        assert replay.json()["status"] == "completed"
        conflicting = await client.post(
            path, headers=headers, json={**body, "patch": {"budget_twd": "800"}}
        )
        assert conflicting.status_code == 409
        assert PlanStore(engine).read(plan.id, actor.actor_id).conditions_revision == 2


async def test_untrusted_base_snapshot_cannot_change_unmentioned_fields(patch_context):
    engine, actor, plan, _, app, headers, body = patch_context
    forged = {
        **body,
        "baseConditions": {**body["baseConditions"], "goal": "偷偷換成另一個目標"},
    }
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/plans/{plan.id}/conditions/patch", headers=headers, json=forged
        )
    assert response.status_code == 409
    assert PlanStore(engine).read(plan.id, actor.actor_id).conditions == plan.conditions


async def test_patch_retains_existing_auth_owner_and_revision_fences(
    patch_context, signed_tokens
):
    engine, actor, plan, _, app, headers, body = patch_context
    _, sign = signed_tokens
    path = f"/api/v1/plans/{plan.id}/conditions/patch"
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        anonymous = await client.post(path, json=body)
        assert anonymous.status_code == 401
        foreign = await client.post(
            path,
            headers={"Authorization": f"Bearer {sign(sub='auth0|patch-other')}"},
            json=body,
        )
        assert foreign.status_code == 404
        stale = await client.post(
            path, headers=headers, json={**body, "expectedRevision": 2}
        )
        assert stale.status_code == 409
    current = PlanStore(engine).read(plan.id, actor.actor_id)
    assert current.conditions_revision == 1
    assert current.conditions == plan.conditions


async def test_patch_retry_survives_restoration_of_v1_command_receipt(patch_context):
    engine, actor, plan, activities, app, headers, body = patch_context
    path = f"/api/v1/plans/{plan.id}/conditions/patch"
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        first = await client.post(path, headers=headers, json=body)
        assert first.status_code == 202
        command_id = first.json()["id"]
        await activities.persist_intent(command_id)
        await activities.apply_effect(command_id)
        await activities.persist_result(command_id)
        # Isolated DB rewind fixture; this is not a live pgBackRest restore.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE plans SET conditions_revision=1, "
                    "conditions=CAST(:conditions AS jsonb) WHERE id=:id"
                ),
                {"id": plan.id, "conditions": plan.conditions.canonical_json()},
            )
            connection.execute(
                text("DELETE FROM control_commands WHERE id=:id"), {"id": command_id}
            )
        reconciled = reconcile_control_log(activities.journal, ControlStore(engine))
        assert str(reconciled[0].id) == command_id
        assert reconciled[0].status == "completed"
        retry = await client.post(path, headers=headers, json=body)
        assert retry.status_code == 200
        assert retry.json()["id"] == command_id
        current = PlanStore(engine).read(plan.id, actor.actor_id)
        assert current.conditions_revision == 2
        assert current.conditions.budget_twd == Decimal("900")
