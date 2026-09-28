"""Disposable real PostgreSQL; never connects to an existing project database."""

import subprocess
import time
from uuid import uuid4

import psycopg
import pytest

IMAGE = (
    "postgres:18-alpine@"
    "sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873"
)


@pytest.mark.integration
def test_postgres_transaction_round_trip():
    name = f"whisky-test-{uuid4().hex}"
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
            "--publish",
            "127.0.0.1::5432",
            "--env",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "--env",
            "POSTGRES_DB=whisky_test",
            IMAGE,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        port = (
            subprocess.check_output(["docker", "port", name, "5432/tcp"], text=True)
            .strip()
            .rsplit(":", 1)[1]
        )
        deadline = time.monotonic() + 30
        while True:
            try:
                connection = psycopg.connect(
                    host="127.0.0.1",
                    port=port,
                    user="postgres",
                    dbname="whisky_test",
                    connect_timeout=1,
                )
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "CREATE TEMP TABLE bootstrap_probe (id uuid PRIMARY KEY)"
                )
                identifier = uuid4()
                cursor.execute("INSERT INTO bootstrap_probe VALUES (%s)", (identifier,))
                cursor.execute("SELECT id FROM bootstrap_probe")
                assert cursor.fetchone() == (identifier,)
                cursor.execute("SHOW server_version_num")
                assert int(cursor.fetchone()[0]) >= 180000
    finally:
        subprocess.run(["docker", "stop", name], check=True, capture_output=True)
