"""Source-backed price observations within immutable catalog releases."""

import sqlalchemy as sa
from alembic import op

revision = "0003_catalog_prices"
down_revision = "0002_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_prices",
        sa.Column("release_id", sa.Uuid(), primary_key=True),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("bottle_version_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=True),
        sa.Column("checked_on", sa.Date(), nullable=True),
        sa.Column("reviewed", sa.Boolean(), nullable=False),
        sa.Column("market", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("unconditional", sa.Boolean(), nullable=False),
        sa.CheckConstraint("reviewed", name="catalog_prices_reviewed"),
        sa.CheckConstraint(
            "amount > 0 AND amount NOT IN ('NaN'::numeric, 'Infinity'::numeric)",
            name="catalog_prices_amount",
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
    op.create_index("catalog_prices_item", "catalog_prices", ["release_id", "item_id"])
    op.execute("""CREATE TRIGGER catalog_prices_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON catalog_prices
        FOR EACH ROW EXECUTE FUNCTION catalog_guard_component()""")


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
