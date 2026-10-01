import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from test_comparison_reports_v4 import comparison_commit as comparison_commit

from whisky.bootstrap.api import create_app
from whisky.modules.identity.public import IdentityAccess
from whisky.modules.research.http import observation_router
from whisky.modules.research.report_store import ReportStore

pytestmark = pytest.mark.integration


@pytest.fixture
async def comparison_api(comparison_commit, signed_tokens):
    engine, research, actor, commit, comparison = comparison_commit
    verifier, sign = signed_tokens
    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO identities (issuer,subject,user_id)
                VALUES (:issuer,'auth0|fixture',:owner)
            """),
            dict(issuer=verifier.issuer, owner=actor.id),
        )
    reports = ReportStore(engine)
    saved = reports.save_v4(commit, comparison)
    app = create_app(
        observation_router=observation_router(
            IdentityAccess(engine, verifier), None, store=research, reports=reports
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        yield client, sign, saved, comparison


async def test_owned_comparison_http_keeps_sources_and_legacy_report(comparison_api):
    client, sign, saved, comparison = comparison_api
    headers = {"Authorization": f"Bearer {sign()}"}
    response = await client.get(
        f"/api/v1/reports/{saved.id}/comparison", headers=headers
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["schemaVersion"] == 4
    assert body["reportId"] == str(saved.id)
    assert len(body["comparison"]["candidates"]) == len(comparison.candidates)
    assert all(
        source["url"].startswith("https://")
        for item in body["items"]
        for source in item["sources"]
    )
    legacy = await client.get(f"/api/v1/reports/{saved.id}", headers=headers)
    assert legacy.status_code == 200
    assert legacy.json()["schemaVersion"] == 1
    assert "comparison" not in legacy.json()


async def test_comparison_http_rejects_anonymous_and_foreign_identity(comparison_api):
    client, sign, saved, _ = comparison_api
    path = f"/api/v1/reports/{saved.id}/comparison"
    assert (await client.get(path)).status_code == 401
    response = await client.get(
        path, headers={"Authorization": f"Bearer {sign(sub='auth0|other')}"}
    )
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
