"""A pre-gate API image cannot read a restored private database."""

from pathlib import Path

import psycopg
import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration
GATE_SQL = Path(__file__).resolve().parents[3] / "deploy/database-login-gate.sql"


def test_old_process_login_is_closed_until_current_database_is_reconciled(
    postgres_url,
):
    admin = create_engine(postgres_url)
    runtime_url = str(admin.url.set(username="whisky_runtime"))
    runtime_dsn = runtime_url.replace("postgresql+psycopg://", "postgresql://")
    try:
        with admin.begin() as connection:
            connection.execute(text("CREATE ROLE whisky_runtime LOGIN"))
            connection.execute(
                text(f"REVOKE CONNECT ON DATABASE {admin.url.database} FROM PUBLIC")
            )
            connection.execute(
                text(
                    f"GRANT CONNECT ON DATABASE {admin.url.database} TO whisky_runtime"
                )
            )
            connection.execute(
                text("""
                    CREATE TABLE recovery_gate (
                        id smallint PRIMARY KEY CHECK (id = 1),
                        postmaster_started_at timestamptz NOT NULL,
                        verified_at timestamptz NOT NULL
                    )
                """)
            )
            connection.execute(text("GRANT SELECT ON recovery_gate TO whisky_runtime"))
            connection.execute(
                text("CREATE TABLE private_record (value text NOT NULL)")
            )
            connection.execute(text("INSERT INTO private_record VALUES ('private')"))
            connection.execute(text("GRANT SELECT ON private_record TO whisky_runtime"))

        # Simulate the old image: it only issues its ordinary private-data query.
        with psycopg.connect(runtime_dsn) as old_process:
            row = old_process.execute("SELECT value FROM private_record").fetchone()
            assert row == ("private",)

        with admin.begin() as connection:
            connection.exec_driver_sql(GATE_SQL.read_text())

        with pytest.raises(psycopg.OperationalError, match="reconciliation"):
            psycopg.connect(runtime_dsn, connect_timeout=3)
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(
                runtime_dsn,
                connect_timeout=3,
                options="-c event_triggers=off",
            )

        with admin.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO recovery_gate VALUES
                        (1, pg_postmaster_start_time(), clock_timestamp())
                """)
            )
        with psycopg.connect(runtime_dsn) as old_process:
            row = old_process.execute("SELECT value FROM private_record").fetchone()
            assert row == ("private",)

        with admin.begin() as connection:
            connection.execute(
                text("""
                    UPDATE recovery_gate
                    SET postmaster_started_at =
                        postmaster_started_at - interval '1 second'
                    WHERE id = 1
                """)
            )
        with pytest.raises(psycopg.OperationalError, match="reconciliation"):
            psycopg.connect(runtime_dsn, connect_timeout=3)
    finally:
        with admin.begin() as connection:
            connection.execute(text("DROP OWNED BY whisky_runtime"))
            connection.execute(text("DROP ROLE whisky_runtime"))
        admin.dispose()
