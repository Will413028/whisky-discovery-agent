"""Keep daily fairness counters independent of erasable attempt details."""

from alembic import op

revision = "0022_owner_daily_usage"
down_revision = "0021_library_receipt_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE research_owner_usage_days (
            owner_id uuid NOT NULL,
            day_utc date NOT NULL REFERENCES research_usage_days (day_utc),
            reserved_neurons integer NOT NULL CHECK (reserved_neurons >= 0),
            PRIMARY KEY (owner_id, day_utc)
        )
    """)
    op.execute("""
        INSERT INTO research_owner_usage_days (owner_id,day_utc,reserved_neurons)
        SELECT owner_id,day_utc,sum(reserved_neurons)
        FROM research_usage_attempts WHERE kind='model'
        GROUP BY owner_id,day_utc
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
