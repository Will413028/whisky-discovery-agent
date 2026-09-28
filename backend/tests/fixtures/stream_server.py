"""Local-only synthetic SSE source. Never mounted by the product API."""

import argparse
import asyncio
from datetime import UTC, datetime
from uuid import UUID

import uvicorn
from ag_ui.core import (
    MessagesSnapshotEvent,
    RunStartedEvent,
    StateSnapshotEvent,
)
from ag_ui.encoder import EventEncoder
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from whisky.modules.research.public import TaskView, waiting_event

app = FastAPI()
TASK = "00000000-0000-4000-8000-000000000001"
THREAD = "00000000-0000-4000-8000-000000000002"
QUESTION = "00000000-0000-4000-8000-000000000003"
RUN = "00000000-0000-4000-8000-000000000004"


@app.get("/health")
def health():
    return {"fixture": True}


@app.post("/agent/observe")
async def observe():
    encoder = EventEncoder()

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
