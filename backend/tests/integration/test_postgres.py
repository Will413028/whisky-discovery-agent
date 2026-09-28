"""Real PostgreSQL smoke; the fixture owns its disposable container."""

from uuid import uuid4

import psycopg
import pytest


@pytest.mark.integration
def test_postgres_transaction_round_trip(postgres_url):
    with psycopg.connect(
        postgres_url.replace("postgresql+psycopg://", "postgresql://")
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE TEMP TABLE bootstrap_probe (id uuid PRIMARY KEY)")
            identifier = uuid4()
            cursor.execute("INSERT INTO bootstrap_probe VALUES (%s)", (identifier,))
            cursor.execute("SELECT id FROM bootstrap_probe")
            assert cursor.fetchone() == (identifier,)
            cursor.execute("SHOW server_version_num")
            assert int(cursor.fetchone()[0]) >= 180000
