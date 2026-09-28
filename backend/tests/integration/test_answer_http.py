"""REST answer uses the same owner-scoped command receipt as AG-UI resume."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from test_catalog_release import synthetic_versioned_release

from whisky.bootstrap.api import create_app
from whisky.bootstrap.migrate import upgrade
from whisky.modules.catalog.store import CatalogStore
from whisky.modules.discovery.conditions import ResearchConditions
from whisky.modules.discovery.store import PlanStore
from whisky.modules.identity.public import IdentityAccess
from whisky.modules.research.answer import AnswerResearch
from whisky.modules.research.clarification import ClarificationStore
from whisky.modules.research.decision import ClarificationDraft
from whisky.modules.research.http import observation_router
from whisky.modules.research.run_store import ResearchRunStore
from whisky.modules.research.store import ResearchStore

pytestmark = pytest.mark.integration


async def test_answer_http_accepts_once_and_exposes_recoverable_command(
    postgres_url, signed_tokens
):
    engine = create_engine(postgres_url)
    upgrade(engine, Path(__file__).parents[2] / "migrations")
    verifier, sign = signed_tokens
    token = sign(sub="auth0|answer-http")
    access = IdentityAccess(engine, verifier)
    session = access.authenticate(token)
    plan = PlanStore(engine).create(
        session.actor_id,
        session.generation,
        "answer-plan",
        ResearchConditions(entry="beginner", goal="探索果香"),
    )
    research = ResearchStore(engine)
    receipt = research.reserve(
        session.actor_id, session.generation, plan.id, 1, "start-answer"
    )
    research.confirm(session.actor_id, session.generation, receipt.id, str(uuid4()))
    context = ResearchRunStore(engine).begin(receipt.task_id)
    clarification = ClarificationStore(engine)
    release = synthetic_versioned_release()
    CatalogStore(engine).publish(release)
    choices = tuple(str(item.bottle.version_id) for item in release.items)
    question = clarification.publish(
        context,
        1,
        ClarificationDraft("哪個版本？", choices),
        datetime.now(UTC) + timedelta(days=7),
    )

    class Answerer:
        async def answer(self, command):
            return clarification.accept_answer(command)

    app = create_app(
        observation_router=observation_router(
            access,
            None,
            store=research,
            answers=AnswerResearch(clarification, Answerer()),
        )
    )
    path = f"/api/v1/tasks/{receipt.task_id}/clarifications/{question.id}/answer"
    body = {
        "key": "answer-once",
        "waitingVersion": 1,
        "conditionsRevision": 1,
        "answer": choices[1],
    }
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            first = await client.post(
                path, json=body, headers={"Authorization": f"Bearer {token}"}
            )
            assert first.status_code == 200
            assert first.json()["scope"] == "research.answer"
            assert first.json()["acceptance"] == "accepted"
            second = await client.post(
                path, json=body, headers={"Authorization": f"Bearer {token}"}
            )
            assert second.status_code == 200
            assert second.json()["id"] == first.json()["id"]
            saved = await client.get(
                f"/api/v1/commands/{first.json()['id']}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert saved.status_code == 200
            assert saved.json()["acceptance"] == "accepted"
        assert research.task(receipt.task_id, session.actor_id).status == "researching"
    finally:
        engine.dispose()
