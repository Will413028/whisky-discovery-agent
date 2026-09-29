"""A stale one-shot Compose job cannot reopen a restarted database."""

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from test_control_recovery import PagedJournal

from whisky.bootstrap.api import configured_app
from whisky.bootstrap.control_reconcile import run
from whisky.bootstrap.settings import Settings
from whisky.modules.control.recovery import RecoveryError
from whisky.platform.recovery_gate import (
    RecoveryGateClosed,
    database_epoch,
    install_recovery_gate,
    stamp_recovery_gate,
)

pytestmark = pytest.mark.integration


def test_recovery_gate_requires_fresh_reconciliation_for_every_checkout(
    research_context,
):
    admin, _, _, _ = research_context
    gated = create_engine(admin.url, pool_size=1, max_overflow=0)
    install_recovery_gate(gated)
    try:
        with pytest.raises(RecoveryGateClosed, match="reconciliation"):
            with gated.connect():
                pass

        epoch = database_epoch(admin)
        with pytest.raises(RecoveryGateClosed, match="changed"):
            stamp_recovery_gate(admin, epoch - timedelta(seconds=1))
        stamp_recovery_gate(admin, epoch)
        with gated.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1

        # This is the state a restored database carries from the old server.
        with admin.begin() as connection:
            connection.execute(
                text(
                    "UPDATE recovery_gate SET postmaster_started_at = "
                    "postmaster_started_at - interval '1 second' WHERE id = 1"
                )
            )
        with pytest.raises(RecoveryGateClosed, match="reconciliation"):
            with gated.connect():
                pass

        stamp_recovery_gate(admin, epoch)
        with gated.connect() as connection:
            assert connection.execute(text("SELECT 2")).scalar_one() == 2
    finally:
        gated.dispose()


async def test_private_api_readiness_closes_after_gate_becomes_stale(research_context):
    admin, _, _, _ = research_context
    app = configured_app(
        Settings(
            database_url=str(admin.url),
            issuer="https://tenant.example/",
            audience="whisky",
            recovery_required=True,
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get("/health/ready")).status_code == 503
        stamp_recovery_gate(admin, database_epoch(admin))
        assert (await client.get("/health/ready")).status_code == 200
        with admin.begin() as connection:
            connection.execute(text("DELETE FROM recovery_gate WHERE id=1"))
        assert (await client.get("/health/ready")).status_code == 503
        assert (await client.get("/health/live")).status_code == 200


def test_reconcile_stamps_only_after_both_complete_inventories(
    research_context, monkeypatch
):
    admin, _, _, _ = research_context
    primary = PagedJournal()
    witness = PagedJournal()
    witness.fail_on_page = 1
    journals = {"primary": primary, "witness": witness}
    monkeypatch.setattr(
        "whisky.bootstrap.control_reconcile.OciControlJournal.from_config_file",
        lambda _config, _namespace, bucket: journals[bucket],
    )
    values = {
        "WHISKY_RECOVERY_MODE": "isolated",
        "WHISKY_DATABASE_URL": str(admin.url),
        "WHISKY_OCI_CONTROL_CONFIG_FILE": "/unused/fixture.conf",
        "WHISKY_OCI_NAMESPACE": "fixture",
        "WHISKY_OCI_CONTROL_BUCKET": "primary",
        "WHISKY_OCI_CONTROL_WITNESS_BUCKET": "witness",
    }
    with pytest.raises(RecoveryError, match="list"):
        run(values)
    gated = create_engine(admin.url)
    install_recovery_gate(gated)
    try:
        with pytest.raises(RecoveryGateClosed):
            with gated.connect():
                pass
        witness.fail_on_page = None
        assert run(values) == 0
        with gated.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        gated.dispose()
