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


def configured_values(**changes):
    return {
        "WHISKY_DATABASE_URL": "postgresql+psycopg://fixture",
        "WHISKY_AUTH0_ISSUER": "https://tenant.example/",
        "WHISKY_AUTH0_AUDIENCE": "fixture",
        **changes,
    }


def test_temporal_configuration_is_explicit_and_optional():
    assert Settings.from_environment(configured_values()).temporal is None
    configured = Settings.from_environment(
        configured_values(
            WHISKY_TEMPORAL_ADDRESS="temporal:7233",
            WHISKY_TEMPORAL_NAMESPACE="whisky",
            WHISKY_TEMPORAL_TASK_QUEUE="whisky-research",
        )
    )
    assert configured.temporal.address == "temporal:7233"
    assert configured.temporal.namespace == "whisky"
    assert configured.temporal.task_queue == "whisky-research"


@pytest.mark.parametrize(
    "change",
    [
        {"WHISKY_TEMPORAL_ADDRESS": "temporal:7233"},
        {"WHISKY_TEMPORAL_NAMESPACE": "whisky"},
        {"WHISKY_TEMPORAL_TASK_QUEUE": "queue"},
    ],
)
def test_partial_temporal_configuration_refuses_startup(change):
    with pytest.raises(ValueError):
        Settings.from_environment(configured_values(**change))


@pytest.mark.parametrize(
    "address",
    [
        "https://temporal:7233",
        "user:pass@temporal:7233",
        "temporal:7233/path",
        "temporal:not-a-port",
        "temporal:0",
        "temporal",
    ],
)
def test_temporal_requires_host_and_port_without_credentials(address):
    with pytest.raises(ValueError):
        Settings.from_environment(
            configured_values(
                WHISKY_TEMPORAL_ADDRESS=address,
                WHISKY_TEMPORAL_NAMESPACE="whisky",
                WHISKY_TEMPORAL_TASK_QUEUE="queue",
            )
        )


def test_temporal_without_product_identity_configuration_is_rejected():
    with pytest.raises(ValueError):
        Settings.from_environment({"WHISKY_TEMPORAL_ADDRESS": "temporal:7233"})
