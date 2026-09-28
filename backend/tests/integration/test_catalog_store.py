from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from test_catalog_release import synthetic_priced_release, synthetic_release

from whisky.bootstrap.migrate import upgrade
from whisky.modules.catalog.publication import load_reviewed_release
from whisky.modules.catalog.store import CatalogStore

pytestmark = pytest.mark.integration


def test_published_prices_round_trip_with_exact_decimal_and_source_reference(
    catalog_engine,
):
    release = synthetic_priced_release()
    store = CatalogStore(catalog_engine)
    store.publish(release)
    assert store.prices(release.id, release.items[0].id) == release.prices


def test_candidates_enforce_budget_and_preserve_reference_prices(catalog_engine):
    release = synthetic_priced_release()
    store = CatalogStore(catalog_engine)
    store.publish(release)
    candidates = store.candidates(release.published_at.date(), Decimal("1500.50"))
    assert len(candidates) == 1
    assert candidates[0].release_id == release.id
    assert candidates[0].item.id == release.items[0].id
    assert candidates[0].prices == release.prices
    assert candidates[0].price_upper_bound == Decimal("1500.50")
    assert store.candidates(release.published_at.date(), Decimal("1500.49")) == ()


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
    assert item.reviewed_on == release.items[0].reviewed_on
    assert item.flavor_tags == release.items[0].flavor_tags
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


@pytest.mark.parametrize("age", [30, 31])
def test_candidate_date_policy_applies_to_persisted_prices(catalog_engine, age):
    release = synthetic_priced_release()
    store = CatalogStore(catalog_engine)
    store.publish(release)
    as_of = release.published_at.date() + timedelta(days=age)
    assert len(store.candidates(as_of, Decimal("2000"))) == (1 if age == 30 else 0)
    unrestricted = store.candidates(as_of, None)
    assert len(unrestricted) == 1
    assert bool(unrestricted[0].prices) == (age == 30)
    assert store.prices(release.id, release.items[0].id) == release.prices


def test_latest_withdrawal_does_not_fall_back_to_old_release_price(catalog_engine):
    original = synthetic_priced_release()
    price = original.prices[0]
    observed_at = original.published_at + timedelta(days=1)
    revised = replace(
        original,
        id=uuid4(),
        published_at=observed_at,
        evidence=(
            replace(
                original.evidence[0],
                captured_at=observed_at,
                checked_on=observed_at.date(),
            ),
        ),
        prices=(
            replace(
                price,
                observation=replace(
                    price.observation,
                    amount=None,
                    observed_at=observed_at,
                    checked_on=observed_at.date(),
                ),
            ),
        ),
    )
    store = CatalogStore(catalog_engine)
    store.publish(original)
    store.publish(revised)
    assert store.candidates(observed_at.date(), Decimal("2000")) == ()
    unrestricted = store.candidates(observed_at.date(), None)
    assert len(unrestricted) == 1
    assert unrestricted[0].release_id == revised.id
    assert unrestricted[0].prices == ()
    assert store.prices(original.id, original.items[0].id) == original.prices


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE catalog_prices SET amount=1",
        "DELETE FROM catalog_prices",
    ],
)
def test_published_price_observations_are_immutable(catalog_engine, statement):
    CatalogStore(catalog_engine).publish(synthetic_priced_release())
    with pytest.raises(IntegrityError, match="immutable"):
        with catalog_engine.begin() as connection:
            connection.execute(text(statement))


def test_human_reviewed_real_sample_publishes_with_budget_and_resolvable_citations(
    catalog_engine,
):
    path = Path(__file__).parents[3] / "data/catalog/first-journey.reviewed.json"
    release = load_reviewed_release(path.read_text())
    store = CatalogStore(catalog_engine)
    store.publish(release)
    candidates = store.candidates(release.published_at.date(), Decimal("1000"))
    assert {candidate.item.name for candidate in candidates} == {
        "格蘭菲迪 12 年",
        "格蘭利威 12 年",
    }
    assert {candidate.price_upper_bound for candidate in candidates} == {
        Decimal("978"),
        Decimal("816"),
    }
    assert len(store.candidates(release.published_at.date(), None)) == 3
    for candidate in store.candidates(release.published_at.date(), None):
        for claim in (*candidate.item.facts, *candidate.item.flavor_tags):
            for evidence_id in claim.evidence_ids:
                assert store.evidence(candidate.release_id, evidence_id) is not None


def test_database_price_fk_rejects_another_bottle_evidence(catalog_engine):
    release = synthetic_priced_release()
    CatalogStore(catalog_engine).publish(release)
    parameters = {"old": release.id, "new": uuid4(), "version": uuid4()}
    with pytest.raises(IntegrityError) as rejected:
        with catalog_engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO catalog_releases
                SELECT :new,published_at+interval '1 day',false
                FROM catalog_releases WHERE id=:old"""),
                parameters,
            )
            connection.execute(
                text("""INSERT INTO catalog_items
                SELECT :new,id,bottle_version_id,abv,volume_ml,name,reviewed
                FROM catalog_items WHERE release_id=:old"""),
                parameters,
            )
            connection.execute(
                text("""INSERT INTO catalog_evidence
                SELECT :new,id,source_id,:version,url,captured_at,checked_on,reviewed
                FROM catalog_evidence WHERE release_id=:old"""),
                parameters,
            )
            connection.execute(
                text("""INSERT INTO catalog_prices
                SELECT :new,id,item_id,evidence_id,bottle_version_id,amount,
                    checked_on,reviewed,market,currency,unconditional
                FROM catalog_prices WHERE release_id=:old"""),
                parameters,
            )
    assert rejected.value.orig.sqlstate == "23503"


def test_legacy_snapshot_with_unknown_metadata_remains_resolvable(catalog_engine):
    release = synthetic_release()
    store = CatalogStore(catalog_engine)
    store.publish(release)
    legacy_id = uuid4()
    tables = (
        "catalog_items",
        "catalog_evidence",
        "catalog_claims",
        "catalog_citations",
    )
    metadata = MetaData()
    metadata.reflect(bind=catalog_engine, only=list(tables))
    with catalog_engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO catalog_releases (id,published_at,sealed)
            VALUES (:id,:published_at,false)"""),
            {"id": legacy_id, "published_at": release.published_at - timedelta(days=1)},
        )
        for name in tables:
            table = metadata.tables[name]
            for row in connection.execute(
                select(table).where(table.c.release_id == release.id)
            ).mappings():
                values = dict(row)
                values["release_id"] = legacy_id
                for column in ("publisher", "method", "method_version", "reviewed_on"):
                    if column in values:
                        values[column] = None
                connection.execute(table.insert().values(**values))
        connection.execute(
            text("UPDATE catalog_releases SET sealed=true WHERE id=:id"),
            {"id": legacy_id},
        )
    item = store.item(legacy_id, release.items[0].id)
    assert item is not None
    assert item.name == release.items[0].name
    assert item.reviewed_on is None
    assert item.flavor_tags[0].method is None
    assert store.evidence(legacy_id, release.evidence[0].id).publisher is None
    with pytest.raises(ValueError):
        from whisky.modules.catalog.domain import validate_release

        validate_release(replace(release, items=(item,)))
