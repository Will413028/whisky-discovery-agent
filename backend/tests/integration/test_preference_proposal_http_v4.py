import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from test_preference_proposal_read_v4 import visible_proposal as visible_proposal

from whisky.bootstrap.api import create_app
from whisky.modules.identity.public import IdentityAccess
from whisky.modules.research.http import observation_router
from whisky.modules.research.store import ResearchStore

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("available", [True, False])
async def test_proposal_http_has_private_typed_view_and_fail_closed_dependencies(
    visible_proposal, signed_tokens, available
):
    engine, actor, plan, task_id, question, source, draft = visible_proposal
    verifier, sign = signed_tokens
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO identities(issuer,subject,user_id) "
                "VALUES (:issuer,'auth0|fixture',:owner)"
            ),
            dict(issuer=verifier.issuer, owner=actor.id),
        )
    app = create_app(
        observation_router=observation_router(
            IdentityAccess(engine, verifier),
            None,
            store=ResearchStore(engine) if available else None,
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        path = f"/api/v1/tasks/{task_id}/preference-proposal"
        assert (await client.get(path)).status_code == 401
        response = await client.get(path, headers={"Authorization": f"Bearer {sign()}"})
        assert response.status_code == (200 if available else 503), response.text
        assert response.headers["cache-control"] == "no-store"
        if not available:
            return
        view = response.json()
        assert view["schemaVersion"] == 4
        assert view["planId"] == str(plan.id) and view["questionId"] == str(question.id)
        assert view["sourceText"] == source
        assert view["proposal"]["preferences"][0]["certainty"] == "inferred"
        foreign = await client.get(
            path, headers={"Authorization": f"Bearer {sign(sub='other')}"}
        )
        assert (
            foreign.status_code == 404
            and foreign.headers["cache-control"] == "no-store"
        )
