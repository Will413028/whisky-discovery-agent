"""Temporal process entry point."""

import argparse
import asyncio
import os
import re
from collections.abc import Mapping
from pathlib import Path

from openai import AsyncOpenAI
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
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
from whisky.modules.control.journal import ControlJournal, MirroredControlJournal
from whisky.modules.control.journal_oci import OciControlJournal
from whisky.modules.control.store import ControlStore
from whisky.modules.control.workflow import ControlWorkflow
from whisky.modules.research.activities import ResearchActivities
from whisky.modules.research.agent import configure_research_agent
from whisky.modules.research.agent_v2 import configure_research_agent_v2
from whisky.modules.research.agent_v3 import configure_research_agent_v3
from whisky.modules.research.agent_v4 import configure_research_agents_v4
from whisky.modules.research.history_cleanup import TemporalResearchHistoryPurger
from whisky.modules.research.history_cleanup_activities import HistoryCleanupActivities
from whisky.modules.research.history_cleanup_schedule import (
    ensure_history_cleanup_schedule,
)
from whisky.modules.research.history_cleanup_workflow import (
    ResearchHistoryCleanupWorkflow,
)
from whisky.modules.research.model import QuotaModel
from whisky.modules.research.quota import DEFAULT_MODEL, QuotaStore
from whisky.modules.research.source_reader import SourceReader
from whisky.modules.research.workflow import ResearchWorkflow
from whisky.modules.research.workflow_v2 import ResearchWorkflowV2
from whisky.modules.research.workflow_v3 import ResearchWorkflowV3
from whisky.modules.research.workflow_v4 import ResearchWorkflowV4
from whisky.platform.recovery_gate import assert_recovery_ready, install_recovery_gate

WORKERS_AI_MODEL = DEFAULT_MODEL


def cloudflare_token_from_values(values: Mapping[str, str]) -> str:
    inline = values.get("WHISKY_CLOUDFLARE_AI_TOKEN", "")
    token_file = values.get("WHISKY_CLOUDFLARE_AI_TOKEN_FILE", "")
    if inline and token_file:
        raise ValueError("Workers AI token source must be unique")
    if token_file:
        if not Path(token_file).is_absolute():
            raise ValueError("Workers AI token file must be absolute")
        return Path(token_file).read_text(encoding="utf-8").strip()
    return inline


def control_journal_from_values(values: Mapping[str, str]) -> ControlJournal | None:
    config_file = values.get("WHISKY_OCI_CONTROL_CONFIG_FILE", "")
    namespace = values.get("WHISKY_OCI_NAMESPACE", "")
    bucket = values.get("WHISKY_OCI_CONTROL_BUCKET", "")
    witness_bucket = values.get("WHISKY_OCI_CONTROL_WITNESS_BUCKET", "")
    configured = (config_file, namespace, bucket, witness_bucket)
    if not any(configured):
        return None
    if (
        not all(configured)
        or not config_file.startswith("/")
        or bucket == witness_bucket
    ):
        raise ValueError("OCI control journal requires complete absolute configuration")
    return MirroredControlJournal(
        OciControlJournal.from_config_file(config_file, namespace, bucket),
        OciControlJournal.from_config_file(config_file, namespace, witness_bucket),
    )


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


def cloudflare_model(
    account_id: str, token: str, *, model_name: str = WORKERS_AI_MODEL
) -> Model:
    if not re.fullmatch(r"[0-9a-fA-F]{32}", account_id) or not token.strip():
        raise ValueError("Workers AI account ID and token must be configured")
    base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
    client = AsyncOpenAI(base_url=base_url, api_key=token, max_retries=0)
    if model_name == "@cf/openai/gpt-oss-20b":
        return OpenAIResponsesModel(
            model_name, provider=OpenAIProvider(openai_client=client)
        )
    return OpenAIChatModel(model_name, provider=OpenAIProvider(openai_client=client))


def research_worker(
    client: Client,
    task_queue: str,
    engine: Engine,
    model: Model,
    *,
    control_journal: ControlJournal | None = None,
    quota: QuotaStore | None = None,
    source_reader: SourceReader | None = None,
) -> Worker:
    if quota is not None:
        model = QuotaModel(model, quota)
    configure_research_agent(engine, model)
    configure_research_agent_v2(engine, model)
    configure_research_agent_v3(model)
    configure_research_agents_v4(model)
    db = ResearchActivities(engine, quota=quota, source_reader=source_reader)
    cleanup = HistoryCleanupActivities(engine, TemporalResearchHistoryPurger(client))
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
            "whisky.modules.research.agent_v3",
            "whisky.modules.research.agent_v4",
            "whisky.modules.research.proposal_agent_v4",
        )
    )
    return Worker(
        client,
        task_queue=task_queue,
        workflows=[
            BootstrapProbe,
            ResearchWorkflow,
            ResearchWorkflowV2,
            ResearchWorkflowV3,
            ResearchWorkflowV4,
            ResearchHistoryCleanupWorkflow,
            *([ControlWorkflow] if control is not None else []),
        ],
        activities=[
            cleanup.page,
            cleanup.erase,
            db.begin_research,
            db.begin_research_v2,
            db.begin_research_v3,
            db.begin_research_v4,
            db.publish_preference_question_v4,
            db.proposal_mappings_v4,
            db.catalog_snapshot_v3,
            db.read_source_v3,
            db.save_report,
            db.save_report_v4,
            db.fail_research,
            db.publish_question,
            db.publish_question_v3,
            db.publish_question_v4,
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
    token = cloudflare_token_from_values(values)
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
    control_journal = control_journal_from_values(values)
    client = await Client.connect(
        address, namespace=namespace, plugins=[PydanticAIPlugin()]
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        if values.get("WHISKY_RECOVERY_REQUIRED", "") not in {"", "0", "1"}:
            raise ValueError("Recovery required flag must be 0 or 1")
        if values.get("WHISKY_RECOVERY_REQUIRED") == "1":
            install_recovery_gate(engine)
            assert_recovery_ready(engine)
        quota = QuotaStore(
            engine,
            daily_neuron_limit=int(values.get("WHISKY_DAILY_MODEL_NEURONS", "0")),
        )
        await ensure_history_cleanup_schedule(client, task_queue)
        await research_worker(
            client,
            task_queue,
            engine,
            cloudflare_model(account_id, token),
            control_journal=control_journal,
            quota=quota,
        ).run()
    finally:
        engine.dispose()
