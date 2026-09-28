"""Temporal process entry point."""

import argparse
import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from whisky.bootstrap.probe import BootstrapProbe


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--task-queue", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.address, args.namespace, args.task_queue))


async def run(address: str, namespace: str, task_queue: str) -> None:
    client = await Client.connect(address, namespace=namespace)
    worker = Worker(client, task_queue=task_queue, workflows=[BootstrapProbe])
    await worker.run()
