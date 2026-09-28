"""Temporal process entry point."""

import argparse
import asyncio
import os
import re
from collections.abc import Mapping

from openai import AsyncOpenAI
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from sqlalchemy import Engine, create_engine
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)

from whisky.bootstrap.probe import BootstrapProbe
from whisky.modules.control.activities import (
    ControlActivities,
    TemporalResearchCanceller,
)
from whisky.modules.control.journal import ControlJournal
from whisky.modules.control.store import ControlStore
from whisky.modules.control.workflow import ControlWorkflow
from whisky.modules.research.activities import ResearchActivities
from whisky.modules.research.agent import configure_research_agent
from whisky.modules.research.agent_v2 import configure_research_agent_v2
from whisky.modules.research.workflow import ResearchWorkflow
from whisky.modules.research.workflow_v2 import ResearchWorkflowV2

WORKERS_AI_MODEL = "@cf/zai-org/glm-4.7-flash"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--task-queue", required=True)
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        run(
            args.address,
            args.namespace,
            args.task_queue,
            os.environ,
            probe_only=args.probe_only,
        )
    )


def cloudflare_model(account_id: str, token: str) -> OpenAIChatModel:
    if not re.fullmatch(r"[0-9a-fA-F]{32}", account_id) or not token.strip():
        raise ValueError("Workers AI account ID and token must be configured")
    base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
    client = AsyncOpenAI(base_url=base_url, api_key=token, max_retries=0)
    return OpenAIChatModel(
        WORKERS_AI_MODEL, provider=OpenAIProvider(openai_client=client)
    )


def research_worker(
    client: Client,
    task_queue: str,
    engine: Engine,
    model: Model,
    *,
    control_journal: ControlJournal | None = None,
) -> Worker:
    configure_research_agent(engine, model)
    configure_research_agent_v2(engine, model)
    db = ResearchActivities(engine)
    control = (
        ControlActivities(
            ControlStore(engine), control_journal, TemporalResearchCanceller(client)
        )
        if control_journal is not None
        else None
    )
    runner = SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules(
            "whisky.modules.research.agent",
            "whisky.modules.research.agent_v2",
        )
    )
    return Worker(
        client,
        task_queue=task_queue,
        workflows=[
            BootstrapProbe,
            ResearchWorkflow,
            ResearchWorkflowV2,
            *([ControlWorkflow] if control is not None else []),
        ],
        activities=[
            db.begin_research,
            db.begin_research_v2,
            db.save_report,
            db.fail_research,
            db.publish_question,
            db.accept_answer,
            db.expire_question,
            *(
                [
                    control.persist_intent,
                    control.apply_effect,
                    control.persist_result,
                    control.notify_research,
                ]
                if control is not None
                else []
            ),
        ],
        workflow_runner=runner,
    )


async def run(
    address: str,
    namespace: str,
    task_queue: str,
    values: Mapping[str, str] | None = None,
    *,
    probe_only: bool = False,
) -> None:
    if values is None:
        values = os.environ
    database_url = values.get("WHISKY_DATABASE_URL", "")
    account_id = values.get("WHISKY_CLOUDFLARE_ACCOUNT_ID", "")
    token = values.get("WHISKY_CLOUDFLARE_AI_TOKEN", "")
    configured = (database_url, account_id, token)
    if probe_only:
        if not task_queue.startswith("whisky-probe-") or any(configured):
            raise ValueError("Probe-only worker requires an isolated probe queue")
        client = await Client.connect(address, namespace=namespace)
        await Worker(client, task_queue=task_queue, workflows=[BootstrapProbe]).run()
        return
    if not all(configured):
        raise ValueError("Research worker requires database and Workers AI settings")
    if database_url and not database_url.startswith("postgresql+psycopg://"):
        raise ValueError("Research worker requires PostgreSQL with psycopg")
    client = await Client.connect(
        address, namespace=namespace, plugins=[PydanticAIPlugin()]
    )
    engine = create_engine(database_url)
    try:
        await research_worker(
            client, task_queue, engine, cloudflare_model(account_id, token)
        ).run()
    finally:
        engine.dispose()
