"""Keep receipt ownership independent of its replay response format."""

from alembic import op

revision = "0021_library_receipt_scope"
down_revision = "0020_long_term_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE library_commands ADD COLUMN plan_id uuid;
        UPDATE library_commands SET plan_id=(response->>'planId')::uuid
            WHERE scope='conclusions.save';
        ALTER TABLE library_commands ADD CONSTRAINT library_command_plan_scope
            CHECK ((scope='conclusions.save')=(plan_id IS NOT NULL));
        ALTER TABLE library_commands ADD CONSTRAINT library_command_owned_plan
            FOREIGN KEY (plan_id,owner_id) REFERENCES plans(id,owner_id);
        CREATE INDEX library_command_plan_purge
            ON library_commands(owner_id,generation,plan_id)
            WHERE plan_id IS NOT NULL;
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
