"""Persist V4 interpretation inputs without changing legacy task payloads."""

from alembic import op

revision = "0013_research_inputs_v4"
down_revision = "0012_recovery_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE research_v4_inputs (
            task_id uuid PRIMARY KEY,
            owner_id uuid NOT NULL,
            input jsonb NOT NULL,
            CONSTRAINT research_v4_inputs_owned_task FOREIGN KEY (task_id,owner_id)
                REFERENCES research_tasks (id,owner_id),
            CONSTRAINT research_v4_inputs_version CHECK (
                jsonb_typeof(input)='object'
                AND input @> '{"schemaVersion": 4}'::jsonb
            )
        )
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
