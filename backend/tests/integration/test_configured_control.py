"""Opted-in configured API reaches the durable control worker."""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from whisky.bootstrap.api import configured_app
from whisky.bootstrap.settings import Settings
from whisky.modules.control.activities import ControlActivities
from whisky.modules.control.journal import MemoryControlJournal
from whisky.modules.control.store import ControlStore
from whisky.modules.control.workflow import ControlWorkflow
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.public import IdentityAccess

pytestmark = pytest.mark.integration


async def test_configured_control_deletes_through_temporal_and_external_receipts(
    research_context, signed_tokens, monkeypatch
):
    engine, _, _, _ = research_context
    verifier, sign = signed_tokens
    monkeypatch.setattr("whisky.bootstrap.api.TokenVerifier", lambda *_: verifier)
    actor = IdentityAccess(engine, verifier).authenticate(sign())
    plan = PlanStore(engine).create(
        actor.actor_id,
        actor.generation,
        "configured-control",
        ResearchConditions(entry="beginner", goal="控制接線"),
    )
    journal = MemoryControlJournal()
    control = ControlActivities(ControlStore(engine), journal)
    async with await WorkflowEnvironment.start_local() as environment:
        queue = f"test-{uuid4()}"
        temporal_address = environment.client.service_client.config.target_host
        settings = Settings.from_environment(
            {
                "WHISKY_DATABASE_URL": str(engine.url),
                "WHISKY_AUTH0_ISSUER": "https://whisky-fixture.example/",
                "WHISKY_AUTH0_AUDIENCE": "https://whisky-api.example",
                "WHISKY_TEMPORAL_ADDRESS": temporal_address,
                "WHISKY_TEMPORAL_NAMESPACE": environment.client.namespace,
                "WHISKY_TEMPORAL_TASK_QUEUE": queue,
                "WHISKY_CONTROL_ENABLED": "1",
            }
        )
        app = configured_app(settings)
        async with (
            app.router.lifespan_context(app),
            Worker(
                environment.client,
                task_queue=queue,
                workflows=[ControlWorkflow],
                activities=[
                    control.persist_intent,
                    control.apply_effect,
                    control.persist_result,
                    control.notify_research,
                ],
            ),
            AsyncClient(transport=ASGITransport(app), base_url="http://test") as client,
        ):
            token = sign()
            response = await client.post(
                f"/api/v1/plans/{plan.id}/delete",
                headers={"Authorization": f"Bearer {token}"},
                json={"key": str(uuid4())},
            )
            assert response.status_code in {200, 202}
            command_id = response.json()["id"]
            receipt = ControlStore(engine).read(UUID(command_id), actor.actor_id)
            assert receipt is not None
            await environment.client.get_workflow_handle(receipt.workflow_id).result()
            completed = await client.get(
                f"/api/v1/control-commands/{command_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert completed.status_code == 200
            assert completed.json()["status"] == "completed"
            assert len(journal.objects) == 2
            assert PlanStore(engine).read(plan.id, actor.actor_id) is None
