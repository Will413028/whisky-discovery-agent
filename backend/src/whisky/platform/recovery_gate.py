"""Fail closed when this PostgreSQL process has no completed external reconciliation."""

from datetime import datetime
from typing import Any

from sqlalchemy import Engine, event, text
from sqlalchemy.exc import SQLAlchemyError


class RecoveryGateClosed(SQLAlchemyError):
    """The current PostgreSQL instance has not passed control reconciliation."""


def database_epoch(engine: Engine) -> datetime:
    with engine.connect() as connection:
        result = connection.execute(text("SELECT pg_postmaster_start_time()"))
        return result.scalar_one()


def stamp_recovery_gate(engine: Engine, expected_epoch: datetime) -> None:
    """Call only after the complete outside inventory and effects succeed."""
    with engine.begin() as connection:
        stamped = connection.execute(
            text("""
                INSERT INTO recovery_gate
                    (id, postmaster_started_at, verified_at)
                SELECT 1, pg_postmaster_start_time(), clock_timestamp()
                WHERE pg_postmaster_start_time() = :expected_epoch
                ON CONFLICT (id) DO UPDATE SET
                    postmaster_started_at = EXCLUDED.postmaster_started_at,
                    verified_at = EXCLUDED.verified_at
                RETURNING id
            """),
            {"expected_epoch": expected_epoch},
        )
        if stamped.scalar_one_or_none() != 1:
            raise RecoveryGateClosed("database changed during reconciliation")


def install_recovery_gate(engine: Engine) -> None:
    """Check each checkout, including connections reused after a DB restart."""

    @event.listens_for(engine, "checkout")
    def check(dbapi_connection: Any, connection_record: Any, _proxy: Any) -> None:
        cursor = None
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM recovery_gate
                    WHERE id = 1
                      AND postmaster_started_at = pg_postmaster_start_time()
                )
            """)
            row = cursor.fetchone()
            if row is None or row[0] is not True:
                raise RecoveryGateClosed("current database requires reconciliation")
        except RecoveryGateClosed:
            raise
        except Exception as exc:
            connection_record.invalidate(exc)
            raise RecoveryGateClosed("cannot verify database reconciliation") from exc
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass
            try:
                dbapi_connection.rollback()
            except Exception:
                pass


def assert_recovery_ready(engine: Engine) -> None:
    with engine.connect():
        pass
