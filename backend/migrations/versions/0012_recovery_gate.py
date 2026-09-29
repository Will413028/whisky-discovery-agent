"""Bind external-control reconciliation to the running PostgreSQL instance."""

from alembic import op

revision = "0012_recovery_gate"
down_revision = "0011_research_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE recovery_gate (
            id smallint PRIMARY KEY CHECK (id = 1),
            postmaster_started_at timestamptz NOT NULL,
            verified_at timestamptz NOT NULL
        )
    """)
    # Product runtime may observe the gate but cannot mark a restored DB safe.
    op.execute("""
        DO $grant$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'whisky_runtime') THEN
                REVOKE ALL ON TABLE recovery_gate FROM whisky_runtime;
                GRANT SELECT ON TABLE recovery_gate TO whisky_runtime;
            END IF;
        END $grant$
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
