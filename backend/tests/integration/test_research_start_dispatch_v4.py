"""Persisted input, never a retry's request payload, chooses the executor."""

from uuid import uuid4

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.testing import WorkflowEnvironment
from test_comparison_reports_v4 import comparison_commit as comparison_commit
from test_library_conclusions import completed_choice as completed_choice
from test_library_purge import delete
from test_research_inputs_v4 import make_turn

from whisky.modules.research.domain import workflow_id_for
from whisky.modules.research.store import ResearchConflict
from whisky.modules.research.temporal_start import ConnectingTemporalResearchStarter

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("kind", ["plan.delete", "actor.delete"])
def test_deleted_task_cannot_be_dispatched_after_history_cleanup(
    completed_choice, kind
):
    from whisky.modules.research.store import ResearchStore

    engine, actor, report, choice = completed_choice
    delete(engine, actor, choice, kind)
    with pytest.raises(ResearchConflict, match="TASK_NOT_WRITABLE"):
        ResearchStore(engine).workflow_type_for_task(report.task_id)


def test_workflow_type_is_pinned_by_persisted_v4_input(research_context):
    _, store, (actor, _), plan = research_context
    legacy = store.reserve(actor.id, actor.generation, plan.id, 1, "legacy-type")
    current = store.reserve_turn_v4(
        actor.id, actor.generation, make_turn(plan, "current-type")
    )
    assert store.workflow_type_for_task(legacy.task_id) == "ResearchWorkflowV3"
    assert store.workflow_type_for_task(current.task_id) == "ResearchWorkflowV4"
    with pytest.raises(ResearchConflict, match="NOT_FOUND"):
        store.workflow_type_for_task(uuid4())


@pytest.mark.parametrize("version", ["ResearchWorkflowV3", "ResearchWorkflowV4"])
async def test_lazy_starter_dispatches_and_reuses_the_persisted_execution(version):
    task_id = uuid4()
    looked_up = []

    def lookup(current):
        looked_up.append(current)
        return version

    async with await WorkflowEnvironment.start_local() as env:
        starter = ConnectingTemporalResearchStarter(
            "unused-fixture-address",
            "default",
            f"test-dispatch-{uuid4()}",
            workflow_type_for_task=lookup,
        )
        starter._client = env.client
        first = await starter.start(task_id)
        retry = await starter.start(task_id)
        assert first == retry
        description = await env.client.get_workflow_handle(
            workflow_id_for(task_id), run_id=first
        ).describe()
        assert description.workflow_type == version
        assert looked_up == [task_id, task_id, task_id, task_id]


async def test_delete_between_lookup_and_start_rejects_late_acceptance(
    completed_choice,
):
    from whisky.modules.research.store import ResearchStore

    engine, actor, report, choice = completed_choice
    store = ResearchStore(engine)
    first = True

    def lookup(task_id):
        nonlocal first
        executor = store.workflow_type_for_task(task_id)
        if first:
            first = False
            delete(engine, actor, choice, "plan.delete")
        return executor

    async with await WorkflowEnvironment.start_local() as env:
        starter = ConnectingTemporalResearchStarter(
            "unused-fixture-address",
            "default",
            f"late-dispatch-{uuid4()}",
            workflow_type_for_task=lookup,
        )
        starter._client = env.client
        with pytest.raises(ResearchConflict, match="TASK_NOT_WRITABLE"):
            await starter.start(report.task_id)
        history = await env.client.get_workflow_handle(
            workflow_id_for(report.task_id)
        ).fetch_history()
        assert any(
            event.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CANCEL_REQUESTED
            for event in history.events
        )
