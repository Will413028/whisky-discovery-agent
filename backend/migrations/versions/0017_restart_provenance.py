"""Link a new V4 research to its explicitly selected historical source."""

from alembic import op

revision = "0017_restart_provenance"
down_revision = "0016_single_version_confirmation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE research_v4_inputs ADD COLUMN source_task_id uuid;
        ALTER TABLE research_v4_inputs ADD CONSTRAINT research_v4_source_owner
            FOREIGN KEY (source_task_id,owner_id)
                REFERENCES research_tasks (id,owner_id);
        ALTER TABLE research_v4_inputs ADD CONSTRAINT research_v4_source_distinct
            CHECK (source_task_id IS NULL OR source_task_id<>task_id);
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
