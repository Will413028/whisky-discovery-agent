from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, update

from whisky.bootstrap.api import create_app
from whisky.bootstrap.migrate import upgrade
from whisky.modules.identity.public import IdentityAccess, router
from whisky.modules.identity.store import IdentityStore, users
from whisky.modules.identity.tokens import Principal


@pytest.fixture
def identity_engine(postgres_url):
    engine = create_engine(postgres_url)
    try:
        upgrade(engine, Path(__file__).parents[2] / "migrations")
        yield engine
    finally:
        engine.dispose()


@pytest.mark.integration
def test_live_access_rechecks_disabled_and_deleted_actor(
    identity_engine, signed_tokens
):
    from sqlalchemy import delete

    from whisky.modules.identity.store import identities

    verifier, sign = signed_tokens
    actor = IdentityStore(identity_engine).resolve(verifier.verify(sign()))
    access = IdentityAccess(identity_engine, verifier)
    assert access.is_active(actor.id)
    with identity_engine.begin() as connection:
        connection.execute(
            update(users).where(users.c.id == actor.id).values(active=False)
        )
    assert not access.is_active(actor.id)
    with identity_engine.begin() as connection:
        connection.execute(delete(identities).where(identities.c.user_id == actor.id))
        connection.execute(delete(users).where(users.c.id == actor.id))
    assert not access.is_active(actor.id)


@pytest.mark.integration
def test_first_login_creates_stable_internal_actor(postgres_url):
    engine = create_engine(postgres_url)
    try:
        upgrade(engine, Path(__file__).parents[2] / "migrations")
        store = IdentityStore(engine)
        principal = Principal("https://issuer.example/", "auth0|fixture")
        actor = store.resolve(principal)
        assert actor is not None, "first verified login must create an internal actor"
        assert store.resolve(principal) == actor
    finally:
        engine.dispose()


@pytest.mark.integration
async def test_verified_token_reads_own_actor(identity_engine, signed_tokens):
    verifier, sign = signed_tokens
    app = create_app(router(identity_engine, verifier))
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {sign()}"}
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "id" in response.json()


@pytest.mark.integration
async def test_disabled_actor_cannot_read_private_data(identity_engine, signed_tokens):
    verifier, sign = signed_tokens
    actor = IdentityStore(identity_engine).resolve(verifier.verify(sign()))
    with identity_engine.begin() as connection:
        connection.execute(
            update(users).where(users.c.id == actor.id).values(active=False)
        )
    async with AsyncClient(
        transport=ASGITransport(create_app(router(identity_engine, verifier))),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {sign()}"}
        )
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.integration
async def test_actor_resource_reads_own_id(identity_engine, signed_tokens):
    verifier, sign = signed_tokens
    actor = IdentityStore(identity_engine).resolve(verifier.verify(sign()))
    async with AsyncClient(
        transport=ASGITransport(create_app(router(identity_engine, verifier))),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/api/v1/actors/{actor.id}", headers={"Authorization": f"Bearer {sign()}"}
        )
    assert response.status_code == 200
    assert response.json() == {"id": str(actor.id)}


@pytest.mark.integration
async def test_other_actor_is_indistinguishable_from_missing(
    identity_engine, signed_tokens
):
    from uuid import uuid4

    verifier, sign = signed_tokens
    other = IdentityStore(identity_engine).resolve(
        verifier.verify(sign(sub="auth0|other"))
    )
    async with AsyncClient(
        transport=ASGITransport(create_app(router(identity_engine, verifier))),
        base_url="http://test",
    ) as client:
        headers = {"Authorization": f"Bearer {sign()}"}
        foreign = await client.get(f"/api/v1/actors/{other.id}", headers=headers)
        missing = await client.get(f"/api/v1/actors/{uuid4()}", headers=headers)
    assert foreign.status_code == missing.status_code == 404
    foreign_body, missing_body = foreign.json(), missing.json()
    assert foreign_body.pop("request_id") != missing_body.pop("request_id")
    assert foreign_body == missing_body


@pytest.mark.integration
async def test_auth_error_has_safe_contract(identity_engine, signed_tokens):
    verifier, _ = signed_tokens
    async with AsyncClient(
        transport=ASGITransport(create_app(router(identity_engine, verifier))),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/me", headers={"Authorization": "Bearer fixture-invalid"}
        )
    assert response.status_code == 401
    assert response.json().get("code") == "UNAUTHENTICATED"
    assert response.json().get("request_id")
    assert "fixture-invalid" not in response.text


@pytest.mark.integration
def test_concurrent_first_login_has_one_actor_and_no_orphan(identity_engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, local

    from sqlalchemy import event, func, select

    from whisky.modules.identity.store import identities

    barrier, seen = Barrier(4), local()

    def first_lookup(_conn, _cursor, statement, _parameters, _context, _executemany):
        if (
            statement.startswith("SELECT")
            and "identities" in statement
            and not getattr(seen, "done", False)
        ):
            seen.done = True
            barrier.wait(timeout=10)

    event.listen(identity_engine, "after_cursor_execute", first_lookup)
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            actors = list(
                executor.map(
                    lambda _: IdentityStore(identity_engine).resolve(
                        Principal("https://issuer.example/", "race")
                    ),
                    range(4),
                )
            )
    finally:
        event.remove(identity_engine, "after_cursor_execute", first_lookup)
    assert len({actor.id for actor in actors}) == 1
    with identity_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(users)) == 1
        assert connection.scalar(select(func.count()).select_from(identities)) == 1
