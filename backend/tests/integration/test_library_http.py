import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from test_comparison_reports_v4 import comparison_commit as comparison_commit
from test_library_conclusions import completed_choice as completed_choice

from whisky.bootstrap.api import create_app
from whisky.modules.identity.public import IdentityAccess
from whisky.modules.library.http import library_router
from whisky.modules.library.store import LibraryStore

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "suffix", ["?limit=0", "?cursor=bad", "?limit=2&limit=3", "?planId=unexpected"]
)
async def test_feedback_query_rejects_invalid_or_duplicate_inputs(library_api, suffix):
    client, sign, _, _ = library_api
    response = await client.get(
        "/api/v1/library/feedback" + suffix,
        headers={"Authorization": f"Bearer {sign()}"},
    )
    assert response.status_code == 422


async def test_feedback_http_saves_reopens_and_lists_only_own_tasting(library_api):
    client, sign, choice, _ = library_api
    headers = {"Authorization": f"Bearer {sign()}"}
    body = dict(
        schemaVersion=1,
        key="favorite-http",
        bottleVersionId=str(choice.selected_version_id),
        expectedRevision=0,
        wantToExplore=True,
        tasting="not_tasted",
        tastingReason="",
    )
    response = await client.post("/api/v1/library/feedback", headers=headers, json=body)
    assert response.status_code == 201, (
        "private feedback requires a typed durable HTTP entry"
    )
    path = f"/api/v1/library/feedback/{choice.selected_version_id}"
    read = await client.get(path, headers=headers)
    assert read.status_code == 200 and read.json() == response.json()
    assert read.headers["cache-control"] == "no-store"
    page = await client.get("/api/v1/library/feedback", headers=headers)
    assert page.status_code == 200 and page.json()["items"] == [response.json()]
    assert (await client.get(path)).status_code == 401
    foreign = {"Authorization": f"Bearer {sign(sub='auth0|other')}"}
    assert (await client.get(path, headers=foreign)).status_code == 404
    assert (await client.get("/api/v1/library/feedback", headers=foreign)).json()[
        "items"
    ] == []


async def test_revisit_returns_current_price_basis_without_exposing_foreign_history(
    library_api,
):
    client, sign, command, _ = library_api
    headers = {"Authorization": f"Bearer {sign()}"}
    saved = await client.post(
        "/api/v1/library/conclusions",
        headers=headers,
        json=command.model_dump(mode="json", by_alias=True),
    )
    path = f"/api/v1/library/conclusions/{saved.json()['id']}/revisit"
    response = await client.get(path, headers=headers)
    assert response.status_code == 200, (
        "private conclusion reopening needs a current qualification endpoint"
    )
    assert response.json()["conclusionId"] == saved.json()["id"]
    assert response.headers["cache-control"] == "no-store"
    assert (await client.get(path)).status_code == 401
    assert (
        await client.get(
            path, headers={"Authorization": f"Bearer {sign(sub='auth0|other')}"}
        )
    ).status_code == 404


async def test_owned_completed_report_supplies_conclusion_parent_context(library_api):
    client, sign, command, report = library_api
    path = f"/api/v1/library/reports/{report.id}/conclusion-context"
    response = await client.get(path, headers={"Authorization": f"Bearer {sign()}"})
    assert response.status_code == 200
    assert response.json() == {
        "schemaVersion": 1,
        "planId": str(command.plan_id),
        "taskId": str(report.task_id),
        "reportId": str(report.id),
        "conditionsRevision": 1,
        "currentConditionsRevision": 1,
    }
    assert response.headers["cache-control"] == "no-store"
    assert (await client.get(path)).status_code == 401
    foreign = await client.get(
        path, headers={"Authorization": f"Bearer {sign(sub='auth0|other')}"}
    )
    assert foreign.status_code == 404


@pytest.fixture
async def library_api(completed_choice, signed_tokens):
    engine, actor, report, command = completed_choice
    verifier, sign = signed_tokens
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO identities (issuer,subject,user_id) "
                "VALUES (:issuer,'auth0|fixture',:owner)"
            ),
            {"issuer": verifier.issuer, "owner": actor.id},
        )
    app = create_app(
        library_router=library_router(
            IdentityAccess(engine, verifier), LibraryStore(engine)
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        yield client, sign, command, report


async def test_signed_user_saves_and_reopens_a_conclusion_with_no_store(library_api):
    client, sign, command, report = library_api
    headers = {"Authorization": f"Bearer {sign()}"}
    response = await client.post(
        "/api/v1/library/conclusions",
        headers=headers,
        json=command.model_dump(mode="json", by_alias=True),
    )
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["reportId"] == str(report.id)
    assert body["conditionsRevision"] == 1
    assert body["reason"] == command.reason
    reopened = await client.get(
        f"/api/v1/library/conclusions/{body['id']}", headers=headers
    )
    assert reopened.status_code == 200 and reopened.json() == body
    assert reopened.headers["cache-control"] == "no-store"


async def test_library_authentication_and_foreign_report_are_not_bypassed(library_api):
    client, sign, command, _ = library_api
    raw = command.model_dump(mode="json", by_alias=True)
    assert (
        await client.post("/api/v1/library/conclusions", json=raw)
    ).status_code == 401
    response = await client.post(
        "/api/v1/library/conclusions",
        headers={"Authorization": f"Bearer {sign(sub='auth0|other')}"},
        json=raw,
    )
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"


async def test_a_new_private_view_finds_saved_conclusions_by_plan(library_api):
    client, sign, command, _ = library_api
    headers = {"Authorization": f"Bearer {sign()}"}
    saved = await client.post(
        "/api/v1/library/conclusions",
        headers=headers,
        json=command.model_dump(mode="json", by_alias=True),
    )
    assert saved.status_code == 201
    response = await client.get(
        f"/api/v1/library/conclusions?planId={command.plan_id}&limit=1", headers=headers
    )
    assert response.status_code == 200
    assert response.json()["items"] == [saved.json()]
    assert response.json()["planId"] == str(command.plan_id)
    assert response.json()["nextCursor"] is None
    assert response.headers["cache-control"] == "no-store"
    foreign = await client.get(
        f"/api/v1/library/conclusions?planId={command.plan_id}",
        headers={"Authorization": f"Bearer {sign(sub='auth0|other')}"},
    )
    assert foreign.status_code == 404


@pytest.mark.parametrize(
    "suffix", ["&limit=0", "&limit=1&limit=2", "&unexpected=1", "&cursor=not-a-cursor"]
)
async def test_invalid_or_duplicate_pagination_inputs_are_rejected(library_api, suffix):
    client, sign, command, _ = library_api
    response = await client.get(
        f"/api/v1/library/conclusions?planId={command.plan_id}{suffix}",
        headers={"Authorization": f"Bearer {sign()}"},
    )
    assert response.status_code == 422
