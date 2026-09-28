"""A worker on the production queue must be able to execute research."""

import pytest

from whisky.bootstrap.worker import run


@pytest.mark.asyncio
async def test_missing_research_configuration_fails_before_queue_polling():
    with pytest.raises(ValueError, match="requires database and Workers AI"):
        await run("127.0.0.1:7233", "default", "shared-queue", {})
