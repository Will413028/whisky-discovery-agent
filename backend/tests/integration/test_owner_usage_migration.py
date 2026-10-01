"""Upgrade retains pre-existing conservative owner/day charges."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.store import IdentityStore
from whisky.modules.identity.tokens import Principal
from whisky.modules.research.store import ResearchStore

pytestmark = pytest.mark.integration


def test_owner_usage_backfill_preserves_finished_and_unknown_charges(postgres_url):
    engine = create_engine(postgres_url)
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).parents[2] / "migrations")
    )
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0021_library_receipt_scope")
        actor = IdentityStore(engine).resolve(
            Principal("https://usage-migration.example/", "synthetic")
        )
        plan = PlanStore(engine).create(
            actor.id,
            actor.generation,
            "usage",
            ResearchConditions(entry="beginner", goal="合成用量升級"),
        )
        task = ResearchStore(engine).reserve(
            actor.id, actor.generation, plan.id, 1, "migration"
        )
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO research_usage_days VALUES (CURRENT_DATE,800)")
            )
            for kind, status, neurons in (
                ("model", "completed", 300),
                ("model", "unknown", 500),
                ("reader", "completed", 0),
            ):
                connection.execute(
                    text("""
                    INSERT INTO research_usage_attempts
                        (id,task_id,owner_id,activity_id,attempt,kind,model_name,
                         status,day_utc,reserved_input_tokens,reserved_output_tokens,
                         reserved_neurons,finished_at)
                    VALUES (:id,:task,:owner,:activity,1,:kind,:model,:status,
                        CURRENT_DATE,0,0,:neurons,now())
                    """),
                    dict(
                        id=uuid4(),
                        task=task.task_id,
                        owner=actor.id,
                        activity=kind + status,
                        kind=kind,
                        status=status,
                        model="@cf/qwen/qwen3-30b-a3b-fp8" if kind == "model" else None,
                        neurons=neurons,
                    ),
                )
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            assert (
                connection.scalar(
                    text(
                        "SELECT reserved_neurons FROM research_owner_usage_days "
                        "WHERE owner_id=:owner"
                    ),
                    dict(owner=actor.id),
                )
                == 800
            )
            connection.execute(text("DELETE FROM research_usage_attempts"))
            assert (
                connection.scalar(
                    text(
                        "SELECT reserved_neurons FROM research_owner_usage_days "
                        "WHERE owner_id=:owner"
                    ),
                    dict(owner=actor.id),
                )
                == 800
            )
    finally:
        engine.dispose()
