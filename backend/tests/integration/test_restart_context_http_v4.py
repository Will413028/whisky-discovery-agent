from uuid import uuid4

import pytest
from sqlalchemy import text
from test_comparison_http_v4 import comparison_api as comparison_api
from test_comparison_reports_v4 import comparison_commit as comparison_commit

pytestmark = pytest.mark.integration


async def test_restart_context_preserves_the_saved_direction_without_starting_a_task(
    comparison_api, comparison_commit
):
    client, sign, saved, comparison = comparison_api
    engine, *_ = comparison_commit
    with engine.connect() as connection:
        plan_id = connection.scalar(
            text("SELECT plan_id FROM research_tasks WHERE id=:task"),
            {"task": saved.task_id},
        )
        before = connection.scalar(text("SELECT count(*) FROM research_tasks"))
    response = await client.get(
        f"/api/v1/plans/{plan_id}/tasks/{saved.task_id}/restart-context",
        headers={"Authorization": f"Bearer {sign()}"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["schemaVersion"] == 4
    assert body["planId"] == str(plan_id)
    assert body["taskId"] == str(saved.task_id)
    assert body["sourceConditionsRevision"] == 1
    assert body["input"]["phase"] == "research"
    assert body["input"]["sourceText"] is None
    assert body["input"]["intent"] == comparison.intent.model_dump(mode="json")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM research_tasks")) == before


async def test_restart_context_rejects_anonymous_foreign_and_wrong_plan(
    comparison_api, comparison_commit
):
    client, sign, saved, _ = comparison_api
    engine, *_ = comparison_commit
    with engine.connect() as connection:
        plan_id = connection.scalar(
            text("SELECT plan_id FROM research_tasks WHERE id=:task"),
            {"task": saved.task_id},
        )
    path = f"/api/v1/plans/{plan_id}/tasks/{saved.task_id}/restart-context"
    assert (await client.get(path)).status_code == 401
    foreign = await client.get(
        path, headers={"Authorization": f"Bearer {sign(sub='auth0|other')}"}
    )
    assert foreign.status_code == 404
    assert foreign.headers["cache-control"] == "no-store"
    wrong_plan = await client.get(
        f"/api/v1/plans/{uuid4()}/tasks/{saved.task_id}/restart-context",
        headers={"Authorization": f"Bearer {sign()}"},
    )
    assert wrong_plan.status_code == 404
