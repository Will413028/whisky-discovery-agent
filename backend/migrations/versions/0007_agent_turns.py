"""Bind AG-UI turns to owned research commands and tasks."""

from alembic import op

revision = "0007_agent_turns"
down_revision = "0006_research_acceptance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE research_tasks DROP CONSTRAINT research_tasks_thread_id_key"
    )
    op.execute("ALTER TABLE research_tasks ADD UNIQUE (owner_id, thread_id)")
    op.execute("ALTER TABLE research_tasks ADD UNIQUE (id, owner_id, thread_id)")
    op.execute("ALTER TABLE research_commands ADD UNIQUE (id, task_id, owner_id)")
    op.execute("""
        CREATE TABLE agent_turns (
            owner_id uuid NOT NULL,
            task_id uuid NOT NULL,
            thread_id uuid NOT NULL,
            run_id uuid NOT NULL,
            command_id uuid NOT NULL UNIQUE,
            outcome jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (owner_id, thread_id, run_id),
            FOREIGN KEY (task_id, owner_id, thread_id)
                REFERENCES research_tasks (id, owner_id, thread_id),
            FOREIGN KEY (command_id, task_id, owner_id)
                REFERENCES research_commands (id, task_id, owner_id)
        )
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
