"""Replay the frozen T06 wait before shipping a new workflow worker."""

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import create_engine
from temporalio import workflow
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)

from whisky.modules.research.agent_v2 import configure_research_agent_v2
from whisky.modules.research.workflow_v2 import ResearchWorkflowV2

FROZEN_V2_WAIT = Path(__file__).parent / "fixtures" / "research_v2_waiting_history.json"


def frozen_history() -> WorkflowHistory:
    return WorkflowHistory.from_json(
        "whisky-research-frozen-v2", FROZEN_V2_WAIT.read_text()
    )


@workflow.defn(name="ResearchWorkflowV2")
class IncompatibleResearchWorkflow:
    @workflow.run
    async def run(self, task_id: str) -> str:
        return await workflow.execute_activity(
            "whisky_unexpected_activity_v1",
            task_id,
            start_to_close_timeout=timedelta(seconds=1),
            result_type=str,
        )


async def test_frozen_waiting_history_replays_with_current_v2():
    def model_must_not_run(messages, info):
        raise AssertionError("Replay invoked the model")

    # Agent registration is required by the PydanticAI Temporal plugin. The
    # engine is deliberately never connected: completed activities replay from
    # history and the workflow remains at its human wait.
    engine = create_engine("postgresql+psycopg://fixture:fixture@localhost/fixture")
    try:
        configure_research_agent_v2(engine, FunctionModel(model_must_not_run))
        replayer = Replayer(
            workflows=[ResearchWorkflowV2],
            plugins=[PydanticAIPlugin()],
            workflow_runner=SandboxedWorkflowRunner(
                restrictions=SandboxRestrictions.default.with_passthrough_modules(
                    "whisky.modules.research.agent_v2"
                )
            ),
        )
        await replayer.replay_workflow(frozen_history())
    finally:
        engine.dispose()


async def test_frozen_waiting_history_rejects_changed_commands():
    replayer = Replayer(
        workflows=[IncompatibleResearchWorkflow],
        workflow_runner=UnsandboxedWorkflowRunner(),
    )
    with pytest.raises(
        workflow.NondeterminismError, match="whisky_unexpected_activity_v1"
    ):
        await replayer.replay_workflow(frozen_history())
