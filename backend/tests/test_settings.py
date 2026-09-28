import pytest
from httpx import ASGITransport, AsyncClient

from whisky.bootstrap.api import configured_app
from whisky.bootstrap.settings import Settings


async def test_missing_identity_configuration_fails_closed():
    assert Settings.from_environment({}) is None
    async with AsyncClient(
        transport=ASGITransport(configured_app(None)), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/me")
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"


def test_partial_configuration_refuses_startup():
    with pytest.raises(ValueError):
        Settings.from_environment({"WHISKY_DATABASE_URL": "fixture"})


@pytest.mark.parametrize(
    "issuer",
    [
        "http://tenant.example/",
        "https://tenant.example",
        "https://tenant.example/path/",
        "https://user:pass@tenant.example/",
    ],
)
def test_issuer_is_a_fixed_https_origin(issuer):
    with pytest.raises(ValueError):
        Settings.from_environment(
            {
                "WHISKY_DATABASE_URL": "postgresql+psycopg://fixture",
                "WHISKY_AUTH0_ISSUER": issuer,
                "WHISKY_AUTH0_AUDIENCE": "fixture",
            }
        )
