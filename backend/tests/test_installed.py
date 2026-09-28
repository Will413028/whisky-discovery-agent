"""Run this file against the wheel, from outside the source checkout as well."""

import subprocess
import sys
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from whisky.bootstrap.api import create_app


async def test_installed_api_answers_liveness():
    app = create_app()
    assert app is not None, "installed package must provide an API application"
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_installed_worker_entrypoint():
    result = subprocess.run(
        [str(Path(sys.executable).parent / "whisky-worker"), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--task-queue" in result.stdout, "worker CLI must expose its isolated queue"
