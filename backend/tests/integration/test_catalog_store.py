from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from test_catalog_release import synthetic_release

from whisky.bootstrap.migrate import upgrade
from whisky.modules.catalog.store import CatalogStore

pytestmark = pytest.mark.integration


@pytest.fixture
def catalog_engine(postgres_url):
    engine = create_engine(postgres_url)
    try:
        upgrade(engine, Path(__file__).parents[2] / "migrations")
        yield engine
    finally:
        engine.dispose()


def test_catalog_migration_installs_release_and_resolvable_citation_tables(
    postgres_url,
):
    engine = create_engine(postgres_url)
    try:
        upgrade(engine, Path(__file__).parents[2] / "migrations")
        assert {
            "catalog_releases",
            "catalog_items",
            "catalog_evidence",
            "catalog_claims",
            "catalog_citations",
        } <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_published_item_and_source_are_resolvable_by_immutable_release(catalog_engine):
    release = synthetic_release()
    store = CatalogStore(catalog_engine)
    store.publish(release)
    item = store.item(release.id, release.items[0].id)
    assert item is not None, (
        "a published item must be readable by its release/item reference"
    )
    assert item.name == release.items[0].name
    assert item.bottle == release.items[0].bottle
    assert {fact.field: fact.value for fact in item.facts} == {
        fact.field: fact.value for fact in release.items[0].facts
    }
    for claim in (*item.facts, *item.flavor_tags):
        for identifier in claim.evidence_ids:
            assert store.evidence(release.id, identifier) == release.evidence[0]


@pytest.mark.parametrize(
    "table,assignment",
    [
        ("catalog_releases", "published_at=published_at + interval '1 second'"),
        ("catalog_items", "name='changed'"),
        ("catalog_evidence", "url='https://changed.example'"),
        ("catalog_claims", "value='changed'"),
        ("catalog_citations", "key=key"),
    ],
)
def test_database_rejects_changes_to_every_sealed_release_component(
    catalog_engine, table, assignment
):
    release = synthetic_release()
    CatalogStore(catalog_engine).publish(release)
    with pytest.raises(IntegrityError):
        with catalog_engine.begin() as connection:
            connection.execute(text(f"UPDATE {table} SET {assignment}"))


def test_sealed_citations_cannot_be_deleted(catalog_engine):
    CatalogStore(catalog_engine).publish(synthetic_release())
    with pytest.raises(IntegrityError):
        with catalog_engine.begin() as connection:
            connection.execute(text("DELETE FROM catalog_citations"))


def test_sealed_release_rejects_additional_facts(catalog_engine):
    release = synthetic_release()
    CatalogStore(catalog_engine).publish(release)
    with pytest.raises(IntegrityError, match="immutable"):
        with catalog_engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO catalog_claims
                (release_id,item_id,kind,key,value)
                VALUES (:release_id,:item_id,'fact','new','new')"""),
                {"release_id": release.id, "item_id": release.items[0].id},
            )


def test_new_release_preserves_old_item_and_evidence_references(catalog_engine):
    original = synthetic_release()
    item = original.items[0]
    revised = replace(
        original,
        id=uuid4(),
        published_at=original.published_at + timedelta(days=1),
        items=(
            replace(
                item,
                name="Revised synthetic name",
                facts=tuple(
                    replace(fact, value="Revised synthetic name")
                    if fact.field == "name"
                    else fact
                    for fact in item.facts
                ),
            ),
        ),
        evidence=(replace(original.evidence[0], url="https://revised.example/source"),),
    )
    store = CatalogStore(catalog_engine)
    store.publish(original)
    store.publish(revised)
    assert store.item(original.id, item.id).name == item.name
    assert store.item(revised.id, item.id).name == "Revised synthetic name"
    assert store.evidence(original.id, original.evidence[0].id) == original.evidence[0]
    assert store.evidence(revised.id, original.evidence[0].id) == revised.evidence[0]
    assert store.item(uuid4(), item.id) is None
    assert store.evidence(uuid4(), original.evidence[0].id) is None


def test_failed_publication_rolls_back_every_insert(catalog_engine):
    release = synthetic_release()
    item = release.items[0]
    # A duplicate tag reaches a real DB primary-key violation after earlier inserts.
    invalid = replace(release, items=(replace(item, flavor_tags=item.flavor_tags * 2),))
    with pytest.raises(IntegrityError):
        CatalogStore(catalog_engine).publish(invalid)
    with catalog_engine.connect() as connection:
        for table in (
            "catalog_releases",
            "catalog_items",
            "catalog_evidence",
            "catalog_claims",
            "catalog_citations",
        ):
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0
