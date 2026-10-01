"""Allow an explicit single reviewed version without weakening proposal choices."""

from alembic import op

revision = "0016_single_version_confirmation"
down_revision = "0015_report_comparisons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE clarifications DROP CONSTRAINT clarifications_choices_check
    """)
    op.execute("""
        ALTER TABLE clarifications ADD CONSTRAINT clarifications_choices_check
            CHECK (
                jsonb_typeof(choices) = 'array'
                AND jsonb_array_length(choices) BETWEEN 1 AND 5
                AND (kind = 'version' OR jsonb_array_length(choices) >= 2)
            )
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
