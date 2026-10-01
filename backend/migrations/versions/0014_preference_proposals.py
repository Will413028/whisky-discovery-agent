"""Keep unconfirmed preferences separate from version clarification answers."""

from alembic import op

revision = "0014_preference_proposals"
down_revision = "0013_research_inputs_v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE clarifications ADD COLUMN kind text NOT NULL DEFAULT 'version'
            CHECK (kind IN ('version','preference_proposal'))
    """)
    op.execute("""
        CREATE TABLE preference_proposals (
            task_id uuid PRIMARY KEY,
            plan_id uuid NOT NULL,
            owner_id uuid NOT NULL,
            generation integer NOT NULL,
            conditions_revision integer NOT NULL,
            base_conditions jsonb NOT NULL,
            source_text text NOT NULL
                CHECK (length(btrim(source_text)) BETWEEN 1 AND 2000),
            proposal jsonb NOT NULL,
            prompt_version text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (task_id,owner_id,generation,conditions_revision)
                REFERENCES research_tasks (id,owner_id,generation,conditions_revision),
            FOREIGN KEY (plan_id,owner_id) REFERENCES plans (id,owner_id)
        )
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
