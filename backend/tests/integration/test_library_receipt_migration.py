"""Existing receipt plan scope is backfilled before relational cleanup."""

import json
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

pytestmark = pytest.mark.integration


def test_legacy_receipt_plan_scope_is_backfilled_and_other_scopes_stay_independent(
    postgres_url,
):
    engine = create_engine(postgres_url)
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).parents[2] / "migrations")
    )
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0020_long_term_preferences")
        actor = IdentityStore(engine).resolve(
            Principal("https://receipt-migration.example/", "synthetic")
        )
        plan = PlanStore(engine).create(
            actor.id,
            actor.generation,
            "receipt",
            ResearchConditions(
                entry="beginner", goal="合成 receipt metadata migration"
            ),
        )
        response = {"schemaVersion": 1, "planId": str(plan.id)}
        with engine.begin() as connection:
            for scope, result in (
                ("conclusions.save", response),
                ("feedback.save", {"schemaVersion": 1}),
            ):
                connection.execute(
                    text("""
                        INSERT INTO library_commands
                            (id,owner_id,generation,scope,key,payload_hash,target_id,response)
                        VALUES (:id,:owner,1,:scope,:key,:hash,:target,
                            CAST(:response AS jsonb))
                    """),
                    dict(
                        id=uuid4(),
                        owner=actor.id,
                        scope=scope,
                        key=scope + "-legacy",
                        hash="0" * 64,
                        target=uuid4(),
                        response=json.dumps(result),
                    ),
                )
            print(
                "baseline:",
                connection.scalar(text("SELECT version_num FROM alembic_version")),
                "receipts=",
                connection.scalar(text("SELECT count(*) FROM library_commands")),
            )
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            rows = (
                connection.execute(
                    text("SELECT * FROM library_commands ORDER BY scope")
                )
                .mappings()
                .all()
            )
            assert "plan_id" in rows[0]
            assert rows[0]["plan_id"] == plan.id
            assert rows[0]["response"] == response
            assert rows[1]["plan_id"] is None
    finally:
        engine.dispose()
