import pytest
from httpx import ASGITransport, AsyncClient
from starlette.exceptions import HTTPException

from whisky.bootstrap.api import create_app
from whisky.platform.http_errors import PublicAPIError


@pytest.mark.parametrize(
    "exception,expected",
    [
        (PublicAPIError(409, "EXAMPLE_PUBLIC_CONFLICT"), "EXAMPLE_PUBLIC_CONFLICT"),
        (HTTPException(409, "IDEMPOTENCY_CONFLICT"), "REQUEST_REJECTED"),
        (HTTPException(409, "Bearer fixture-private-detail"), "REQUEST_REJECTED"),
    ],
)
async def test_only_explicit_public_errors_expose_their_code(exception, expected):
    app = create_app()

    @app.get("/api/v1/error-fixture")
    def fail():
        raise exception

    async with AsyncClient(
        transport=ASGITransport(app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/error-fixture")
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == expected
    assert response.json()["request_id"]
    assert response.json()["retryable"] is False
    assert "fixture-private-detail" not in response.text
