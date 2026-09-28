"""Temporal may retry control phases without crossing the external evidence fence."""

import asyncio
from threading import Event
from uuid import uuid4

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.models.function import FunctionModel
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from whisky.bootstrap.worker import research_worker
from whisky.modules.control.journal import MemoryControlJournal
from whisky.modules.control.store import ControlStore
from whisky.modules.control.workflow import ControlWorkflow
from whisky.modules.discovery.conditions import CatalogReference, ResearchConditions
from whisky.modules.discovery.store import PlanStore

pytestmark = pytest.mark.integration


class HeldResultJournal(MemoryControlJournal):
    def __init__(self):
        super().__init__()
        self.result_attempted = Event()
        self.release_result = Event()

    def put_once(self, key, body):
        if key.endswith("/result.json"):
            self.result_attempted.set()
            assert self.release_result.wait(10), "result barrier was never released"
        super().put_once(key, body)


async def test_control_workflow_waits_for_outside_result_before_completion(
    research_context,
):
    engine, research, (actor, _), plan = research_context
    started = research.reserve(actor.id, actor.generation, plan.id, 1, "control")
    controls = ControlStore(engine)
    command = controls.reserve(
        actor.id, actor.generation, "task.cancel", started.task_id, str(uuid4())
    )
    journal = HeldResultJournal()
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-control-{uuid4()}"
        async with research_worker(
            client,
            queue,
            engine,
            FunctionModel(lambda *_: None),
            control_journal=journal,
        ):
            handle = await client.start_workflow(
                ControlWorkflow.run,
                str(command.id),
                id=command.workflow_id,
                task_queue=queue,
            )
            assert await asyncio.to_thread(journal.result_attempted.wait, 10)
            assert controls.read(command.id, actor.id).status == "effect_applied"
            assert research.task(started.task_id, actor.id).status == "cancelled"
            journal.release_result.set()
            assert await asyncio.wait_for(handle.result(), 20) == "completed"
            assert controls.read(command.id, actor.id).status == "completed"
            assert len(journal.objects) == 2


async def test_rejected_condition_change_allows_new_workflow_at_same_revision(
    research_context,
):
    engine, _, (actor, _), plan = research_context
    controls = ControlStore(engine)
    invalid = controls.reserve(
        actor.id,
        actor.generation,
        "plan.change_conditions",
        plan.id,
        str(uuid4()),
        expected_revision=1,
        conditions=ResearchConditions(
            entry="existing_bottle",
            goal="版本有誤",
            starting_bottle=CatalogReference(release_id=uuid4(), item_id=uuid4()),
        ),
    )
    async with await WorkflowEnvironment.start_local() as env:
        client = Client(**{**env.client.config(), "plugins": [PydanticAIPlugin()]})
        queue = f"whisky-control-{uuid4()}"
        async with research_worker(
            client,
            queue,
            engine,
            FunctionModel(lambda *_: None),
            control_journal=MemoryControlJournal(),
        ):
            first = await client.start_workflow(
                ControlWorkflow.run,
                str(invalid.id),
                id=invalid.workflow_id,
                task_queue=queue,
            )
            assert await asyncio.wait_for(first.result(), 20) == "rejected"
            corrected = controls.reserve(
                actor.id,
                actor.generation,
                "plan.change_conditions",
                plan.id,
                str(uuid4()),
                expected_revision=1,
                conditions=ResearchConditions(entry="beginner", goal="修正版"),
            )
            second = await client.start_workflow(
                ControlWorkflow.run,
                str(corrected.id),
                id=corrected.workflow_id,
                task_queue=queue,
            )
            assert await asyncio.wait_for(second.result(), 20) == "completed"
            assert PlanStore(engine).read(plan.id, actor.id).conditions_revision == 2
