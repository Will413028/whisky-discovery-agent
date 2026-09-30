"""Local-only synthetic SSE source. Never mounted by the product API."""

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import uvicorn
from ag_ui.core import (
    MessagesSnapshotEvent,
    RunStartedEvent,
    StateSnapshotEvent,
)
from ag_ui.encoder import EventEncoder
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)

from whisky.modules.library.contracts import ConclusionViewV1, SaveConclusionV1
from whisky.modules.research.public import TaskView, waiting_event

app = FastAPI()
release_snapshot = asyncio.Event()
TASK = "00000000-0000-4000-8000-000000000001"
THREAD = "00000000-0000-4000-8000-000000000002"
QUESTION = "00000000-0000-4000-8000-000000000003"
RUN = "00000000-0000-4000-8000-000000000004"
RESEARCH_TASK = "00000000-0000-4000-8000-000000000011"
RESEARCH_QUESTION = "00000000-0000-4000-8000-000000000012"
RESEARCH_REPORT = "00000000-0000-4000-8000-000000000013"
RESEARCH_PLAN = "00000000-0000-4000-8000-000000000014"
RESEARCH_VERSION_12 = "00000000-0000-4000-8000-000000000015"
RESEARCH_VERSION_15 = "00000000-0000-4000-8000-000000000016"
RESEARCH_FIXTURE = (
    Path(__file__).resolve().parents[3] / "apps/web/.artifacts/research-fixture"
)
research_task: TaskView | None = None
saved_conclusions: list[dict[str, object]] = []


def fixture_auth(request: Request) -> None:
    if request.headers.get("authorization") != "Bearer synthetic-research-token":
        raise HTTPException(401)


@app.post("/__research_fixture/reset")
def reset_research():
    global research_task
    research_task = None
    saved_conclusions.clear()
    return {"reset": True}


@app.get("/research", response_class=HTMLResponse)
@app.get("/research/{task_id}", response_class=HTMLResponse)
@app.get("/plans", response_class=HTMLResponse)
@app.get("/plans/{plan_id}", response_class=HTMLResponse)
@app.get("/plans/{plan_id}/conclusions", response_class=HTMLResponse)
def research_page(task_id: str | None = None, plan_id: str | None = None):
    return HTMLResponse((RESEARCH_FIXTURE / "index.html").read_text())


@app.get("/research-client.js")
def research_client():
    return FileResponse(RESEARCH_FIXTURE / "client.js", media_type="text/javascript")


@app.post("/api/v1/plans")
async def create_research_plan(request: Request):
    fixture_auth(request)
    body = await request.json()
    if not body.get("conditions", {}).get("goal"):
        raise HTTPException(422)
    return JSONResponse(
        {"id": RESEARCH_PLAN, "conditionsRevision": 1},
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )


@app.post("/agent")
async def start_research(request: Request):
    global research_task
    fixture_auth(request)
    body = await request.json()
    if body.get("forwardedProps", {}).get("planId") != RESEARCH_PLAN:
        raise HTTPException(422)
    queued = TaskView(
        task_id=UUID(RESEARCH_TASK),
        thread_id=UUID(body["threadId"]),
        conditions_revision=1,
        view_version=1,
        status="queued",
        stage="等待研究開始",
        question=None,
        report_id=None,
        error=None,
        observed_at=datetime.now(UTC),
    )
    research_task = TaskView.model_validate(
        {
            **queued.model_dump(),
            "view_version": 2,
            "status": "needs_input",
            "stage": "等待版本補充",
            "question": {
                "id": RESEARCH_QUESTION,
                "prompt": "你指的是哪個版本？",
                "choices": [
                    {"id": RESEARCH_VERSION_12, "label": "12 年"},
                    {"id": RESEARCH_VERSION_15, "label": "15 年"},
                ],
                "waitingVersion": 1,
                "expiresAt": "2099-01-01T00:00:00Z",
            },
        }
    )
    encoder = EventEncoder()

    async def events():
        yield encoder.encode(
            RunStartedEvent(thread_id=body["threadId"], run_id=body["runId"])
        )
        yield encoder.encode(
            StateSnapshotEvent(snapshot=queued.model_dump(mode="json", by_alias=True))
        )

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
    )


@app.get("/api/v1/tasks/{task_id}")
def read_research_task(task_id: str, request: Request):
    fixture_auth(request)
    if research_task is None or task_id != RESEARCH_TASK:
        raise HTTPException(404)
    return JSONResponse(
        research_task.model_dump(mode="json", by_alias=True),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/v1/tasks")
def list_research_tasks(request: Request):
    fixture_auth(request)
    return JSONResponse(
        [research_task.model_dump(mode="json", by_alias=True)]
        if research_task is not None
        and research_task.status
        not in {"completed", "failed", "cancelled", "superseded"}
        else [],
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/v1/tasks/{task_id}/clarifications/{question_id}/answer")
async def answer_research(task_id: str, question_id: str, request: Request):
    global research_task
    fixture_auth(request)
    body = await request.json()
    if (
        research_task is None
        or task_id != RESEARCH_TASK
        or question_id != RESEARCH_QUESTION
        or body.get("waitingVersion") != 1
        or body.get("answer") not in (RESEARCH_VERSION_12, RESEARCH_VERSION_15)
    ):
        raise HTTPException(409)
    research_task = TaskView.model_validate(
        {
            **research_task.model_dump(),
            "view_version": 3,
            "status": "completed",
            "stage": "報告完成",
            "question": None,
            "report_id": RESEARCH_REPORT,
        }
    )
    return JSONResponse(
        {
            "id": str(uuid4()),
            "taskId": RESEARCH_TASK,
            "scope": "research.answer",
            "acceptance": "accepted",
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/v1/reports/{report_id}")
def read_research_report(report_id: str, request: Request):
    fixture_auth(request)
    if (
        research_task is None
        or research_task.status != "completed"
        or report_id != RESEARCH_REPORT
    ):
        raise HTTPException(404)
    return JSONResponse(
        {
            "id": RESEARCH_REPORT,
            "taskId": RESEARCH_TASK,
            "summary": "已依補充版本重新查核",
            "candidates": [],
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/v1/library/reports/{report_id}/conclusion-context")
def read_conclusion_context(report_id: str, request: Request):
    fixture_auth(request)
    if research_task is None or research_task.status != "completed":
        raise HTTPException(404)
    if report_id != RESEARCH_REPORT:
        raise HTTPException(404)
    return JSONResponse(
        dict(
            schemaVersion=1,
            planId=RESEARCH_PLAN,
            taskId=RESEARCH_TASK,
            reportId=RESEARCH_REPORT,
            conditionsRevision=1,
            currentConditionsRevision=1,
        ),
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/v1/library/conclusions")
def save_synthetic_conclusion(command: SaveConclusionV1, request: Request):
    fixture_auth(request)
    if (
        str(command.plan_id) != RESEARCH_PLAN
        or str(command.report_id) != RESEARCH_REPORT
        or command.selected_version_id is not None
        or command.expected_conditions_revision != 1
        or research_task is None
        or research_task.status != "completed"
    ):
        raise HTTPException(409)
    view = ConclusionViewV1(
        id=uuid4(),
        plan_id=UUID(RESEARCH_PLAN),
        task_id=UUID(RESEARCH_TASK),
        report_id=UUID(RESEARCH_REPORT),
        conditions_revision=1,
        conditions={"entry": "beginner", "goal": "合成測試果香"},
        catalog_release_id=None,
        evaluated_on=datetime.now(UTC).date(),
        revision=1,
        outcome="no_suitable",
        selected_version_id=None,
        selected_bottle_name=None,
        alternative_version_ids=(),
        reason=command.reason,
        tradeoff=command.tradeoff,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    ).model_dump(mode="json", by_alias=True)
    saved_conclusions.append(view)
    return JSONResponse(view, status_code=201, headers={"Cache-Control": "no-store"})


@app.get("/api/v1/library/conclusions")
def list_synthetic_conclusions(request: Request):
    fixture_auth(request)
    if request.query_params.get("planId") != RESEARCH_PLAN:
        raise HTTPException(404)
    return JSONResponse(
        dict(
            schemaVersion=1,
            planId=RESEARCH_PLAN,
            items=saved_conclusions,
            nextCursor=None,
        ),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health")
def health():
    return {"fixture": True}


@app.post("/__release")
async def release():
    release_snapshot.set()
    return {"released": True}


@app.post("/agent/observe")
async def observe(request: Request):
    encoder = EventEncoder()
    gated = request.headers.get("authorization") == "Bearer synthetic-stream-gate"
    reconnect_first = request.headers.get("authorization") == "Bearer synthetic-token-1"
    if gated:
        release_snapshot.clear()

    async def events():
        view = TaskView(
            task_id=UUID(TASK),
            thread_id=UUID(THREAD),
            conditions_revision=1,
            view_version=1,
            status="researching",
            stage="合成串流測試",
            question=None,
            report_id=None,
            error=None,
            observed_at=datetime.now(UTC),
        )
        yield encoder.encode(RunStartedEvent(thread_id=THREAD, run_id=RUN))
        yield encoder.encode(
            StateSnapshotEvent(snapshot=view.model_dump(mode="json", by_alias=True))
        )
        if reconnect_first:
            return
        if gated:
            async with asyncio.timeout(8):
                await release_snapshot.wait()
        else:
            await asyncio.sleep(0.8)
        waiting = TaskView.model_validate(
            {
                **view.model_dump(),
                "view_version": 2,
                "status": "needs_input",
                "question": {
                    "id": QUESTION,
                    "prompt": "合成測試問題",
                    "waitingVersion": 2,
                    "expiresAt": "2099-01-01T00:00:00Z",
                },
            }
        )
        yield encoder.encode(
            StateSnapshotEvent(snapshot=waiting.model_dump(mode="json", by_alias=True))
        )
        yield encoder.encode(MessagesSnapshotEvent(messages=[]))
        yield encoder.encode(waiting_event(THREAD, RUN, QUESTION))

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port)
