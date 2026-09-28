from pathlib import Path

import pytest
from sqlalchemy import create_engine

from whisky.bootstrap.migrate import upgrade
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.store import IdentityStore
from whisky.modules.identity.tokens import Principal
from whisky.modules.research.store import ResearchStore


@pytest.fixture
def research_context(postgres_url):
    engine = create_engine(postgres_url)
    try:
        upgrade(engine, Path(__file__).parents[2] / "migrations")
        actors = [
            IdentityStore(engine).resolve(
                Principal("https://research-fixture.example/", subject)
            )
            for subject in ("one", "two")
        ]
        plan = PlanStore(engine).create(
            actors[0].id,
            actors[0].generation,
            "plan",
            ResearchConditions(entry="beginner", goal="探索果香"),
        )
        yield engine, ResearchStore(engine), actors, plan
    finally:
        engine.dispose()
