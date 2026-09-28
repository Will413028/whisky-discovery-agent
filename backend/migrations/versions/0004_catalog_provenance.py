"""Preserve source publishers and versioned editorial flavor provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0004_catalog_provenance"
down_revision = "0003_catalog_prices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing immutable snapshots retain unknown metadata rather than invented values.
    op.add_column("catalog_evidence", sa.Column("publisher", sa.Text(), nullable=True))
    op.add_column("catalog_claims", sa.Column("method", sa.Text(), nullable=True))
    op.add_column(
        "catalog_claims", sa.Column("method_version", sa.Text(), nullable=True)
    )
    op.add_column("catalog_items", sa.Column("reviewed_on", sa.Date(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
