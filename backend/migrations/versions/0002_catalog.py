"""Catalog release snapshots and relational source citations."""

import sqlalchemy as sa
from alembic import op

revision = "0002_catalog"
down_revision = "0001_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_releases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=False, unique=True
        ),
        sa.Column("sealed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "catalog_items",
        sa.Column(
            "release_id",
            sa.Uuid(),
            sa.ForeignKey("catalog_releases.id"),
            primary_key=True,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("bottle_version_id", sa.Uuid(), nullable=False),
        sa.Column("abv", sa.Numeric(), nullable=True),
        sa.Column("volume_ml", sa.Integer(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("reviewed", sa.Boolean(), nullable=False),
        sa.CheckConstraint("reviewed", name="catalog_items_reviewed"),
        sa.CheckConstraint("abv > 0 AND abv <= 100", name="catalog_items_abv"),
        sa.CheckConstraint("volume_ml > 0", name="catalog_items_volume"),
        sa.UniqueConstraint("release_id", "id", "bottle_version_id"),
    )
    op.create_table(
        "catalog_evidence",
        sa.Column(
            "release_id",
            sa.Uuid(),
            sa.ForeignKey("catalog_releases.id"),
            primary_key=True,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("bottle_version_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_on", sa.Date(), nullable=False),
        sa.Column("reviewed", sa.Boolean(), nullable=False),
        sa.CheckConstraint("reviewed", name="catalog_evidence_reviewed"),
        sa.UniqueConstraint("release_id", "id", "bottle_version_id"),
    )
    op.create_table(
        "catalog_claims",
        sa.Column("release_id", sa.Uuid(), primary_key=True),
        sa.Column("item_id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(), primary_key=True),
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.CheckConstraint("kind IN ('fact', 'tag')", name="catalog_claims_kind"),
        sa.ForeignKeyConstraint(
            ["release_id", "item_id"], ["catalog_items.release_id", "catalog_items.id"]
        ),
    )
    op.create_table(
        "catalog_citations",
        sa.Column("release_id", sa.Uuid(), primary_key=True),
        sa.Column("item_id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(), primary_key=True),
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("evidence_id", sa.Uuid(), primary_key=True),
        sa.Column("bottle_version_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id", "item_id", "kind", "key"],
            [
                "catalog_claims.release_id",
                "catalog_claims.item_id",
                "catalog_claims.kind",
                "catalog_claims.key",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["release_id", "item_id", "bottle_version_id"],
            [
                "catalog_items.release_id",
                "catalog_items.id",
                "catalog_items.bottle_version_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["release_id", "evidence_id", "bottle_version_id"],
            [
                "catalog_evidence.release_id",
                "catalog_evidence.id",
                "catalog_evidence.bottle_version_id",
            ],
        ),
    )

    op.execute("""
        CREATE FUNCTION catalog_require_unsealed(release_uuid uuid) RETURNS void
        LANGUAGE plpgsql AS $$
        DECLARE is_sealed boolean;
        BEGIN
            SELECT sealed INTO is_sealed FROM catalog_releases
            WHERE id=release_uuid FOR UPDATE;
            IF is_sealed THEN
                RAISE EXCEPTION 'Published catalog releases are immutable'
                    USING ERRCODE='23514';
            END IF;
        END;
        $$
    """)
    op.execute("""
        CREATE FUNCTION catalog_guard_component() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                PERFORM catalog_require_unsealed(OLD.release_id);
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM catalog_require_unsealed(NEW.release_id);
                RETURN NEW;
            END IF;
            RETURN OLD;
        END;
        $$
    """)
    for table in (
        "catalog_items",
        "catalog_evidence",
        "catalog_claims",
        "catalog_citations",
    ):
        op.execute(f"""CREATE TRIGGER {table}_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION catalog_guard_component()""")
    op.execute("""
        CREATE FUNCTION catalog_guard_release() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.sealed THEN
                RAISE EXCEPTION 'Published catalog releases are immutable'
                    USING ERRCODE='23514';
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""CREATE TRIGGER catalog_releases_immutable
        BEFORE UPDATE OR DELETE ON catalog_releases
        FOR EACH ROW EXECUTE FUNCTION catalog_guard_release()""")


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
