import pytest
from sqlalchemy import event
from test_catalog_release import synthetic_release

from whisky.modules.catalog.public import reviewed_flavor_references
from whisky.modules.catalog.store import CatalogStore

pytestmark = pytest.mark.integration


def test_flavor_query_returns_only_exact_reviewed_citations_without_price_reads(
    research_context,
):
    engine = research_context[0]
    release = synthetic_release()
    CatalogStore(engine).publish(release)
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        with engine.connect() as connection:
            result = reviewed_flavor_references(connection, release.id)
        assert len(result) == 1
        assert result[0].release_id == release.id
        assert result[0].item_id == release.items[0].id
        assert result[0].label == "synthetic-fruit"
        assert result[0].evidence_ids == (release.evidence[0].id,)
        assert not any("catalog_prices" in statement for statement in statements)
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def test_empty_or_missing_release_has_no_flavor_references(research_context):
    from uuid import uuid4

    with research_context[0].connect() as connection:
        assert reviewed_flavor_references(connection, None) == ()
        assert reviewed_flavor_references(connection, uuid4()) == ()
