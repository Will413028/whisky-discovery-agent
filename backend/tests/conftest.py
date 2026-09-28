import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from whisky.modules.identity.tokens import TokenVerifier

ISSUER = "https://whisky-fixture.example/"
AUDIENCE = "https://whisky-api.example"


@pytest.fixture
def signed_tokens():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="whisky-fixture", use="sig", alg="RS256")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"keys": [jwk]}).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def sign(**changes):
        claims = dict(
            iss=ISSUER,
            aud=AUDIENCE,
            sub="auth0|fixture",
            iat=int(time.time()),
            exp=int(time.time()) + 60,
        )
        claims.update(changes)
        return jwt.encode(
            claims, key, algorithm="RS256", headers={"kid": "whisky-fixture"}
        )

    try:
        yield (
            TokenVerifier(
                ISSUER, AUDIENCE, f"http://127.0.0.1:{server.server_port}/jwks"
            ),
            sign,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


IMAGE = (
    "postgres:18-alpine@"
    "sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873"
)


@pytest.fixture(scope="session")
def postgres_server_url():
    existing = os.environ.get("WHISKY_TEST_POSTGRES_URL")
    if existing is not None:
        if not existing.startswith(
            "postgresql+psycopg://postgres@127.0.0.1:"
        ) or not existing.endswith("/whisky_test"):
            raise ValueError(
                "External test PostgreSQL must be a dedicated loopback database"
            )
        yield existing
        return
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
        deadline = time.monotonic() + 90
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
        connection.close()
        yield f"postgresql+psycopg://postgres@127.0.0.1:{port}/whisky_test"
    finally:
        subprocess.run(["docker", "stop", name], check=True, capture_output=True)


@pytest.fixture
def postgres_url(postgres_server_url):
    name = f"whisky_{uuid4().hex}"
    with psycopg.connect(
        postgres_server_url.replace("postgresql+psycopg://", "postgresql://"),
        autocommit=True,
    ) as admin:
        admin.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name))
        )
        try:
            yield postgres_server_url.rsplit("/", 1)[0] + "/" + name
        finally:
            admin.execute(
                psycopg.sql.SQL("DROP DATABASE {}").format(psycopg.sql.Identifier(name))
            )
