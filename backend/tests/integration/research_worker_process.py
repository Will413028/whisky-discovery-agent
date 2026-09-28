"""Isolated test worker with a deterministic model and no external model I/O."""

import asyncio
import json
from multiprocessing.connection import Connection

from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import create_engine
from temporalio.client import Client

from whisky.bootstrap.worker import research_worker


def model(messages, info):
    returns = [
        part
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    if not returns:
        return ModelResponse(parts=[ToolCallPart("search_reviewed_catalog", {})])
    options = returns[-1].content
    if isinstance(options, str):
        options = json.loads(options)
    if "Previously clarified: Question:" not in str(messages):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "report": None,
                        "clarification": {
                            "prompt": "你指的是哪個版本？",
                            "choices": [
                                option["bottle_version_id"] for option in options[:2]
                            ],
                        },
                    },
                )
            ]
        )
    option = options[0]
    return ModelResponse(
        parts=[
            ToolCallPart(
                info.output_tools[0].name,
                {
                    "report": {
                        "summary": "跨程序恢復後重新查核",
                        "candidates": [
                            {
                                "release_id": option["release_id"],
                                "item_id": option["item_id"],
                                "claims": [option["facts"][0]],
                                "reason": "來源與版本已核對",
                                "price_ids": option["price_ids"],
                            }
                        ],
                        "unresolved": [],
                    },
                    "clarification": None,
                },
            )
        ]
    )


async def _serve(
    address: str, namespace: str, queue: str, database_url: str, control: Connection
) -> None:
    client = await Client.connect(
        address, namespace=namespace, plugins=[PydanticAIPlugin()]
    )
    engine = create_engine(database_url)
    try:
        async with research_worker(client, queue, engine, FunctionModel(model)):
            control.send("ready")
            await asyncio.to_thread(control.recv)
    finally:
        engine.dispose()


def run_worker(
    address: str, namespace: str, queue: str, database_url: str, control: Connection
) -> None:
    try:
        asyncio.run(_serve(address, namespace, queue, database_url, control))
    except Exception as error:
        control.send(f"error:{type(error).__name__}")
        raise
    finally:
        control.close()
