"""Catalog queries available to other business modules."""

from uuid import UUID

from sqlalchemy import Connection, text


def is_published_item(connection: Connection, release_id: UUID, item_id: UUID) -> bool:
    return bool(
        connection.scalar(
            text("""
        SELECT EXISTS (
            SELECT 1 FROM catalog_items i
            JOIN catalog_releases r ON r.id = i.release_id
            WHERE i.release_id = :release AND i.id = :item AND i.reviewed AND r.sealed
        )
    """),
            dict(release=release_id, item=item_id),
        )
    )
