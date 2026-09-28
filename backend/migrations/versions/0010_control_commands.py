"""Durable control receipts and plan tombstones for cancellation fences."""

from alembic import op

revision = "0010_control_commands"
down_revision = "0009_clarifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE plans ADD COLUMN deleted_at timestamptz")
    op.execute("""
        CREATE TABLE control_commands (
            id uuid PRIMARY KEY,
            owner_id uuid NOT NULL REFERENCES users (id),
            generation integer NOT NULL CHECK (generation >= 1),
            kind text NOT NULL CHECK (kind IN (
                'task.cancel', 'plan.change_conditions',
                'plan.delete', 'actor.delete')),
            target_id uuid NOT NULL,
            target_generation integer NOT NULL CHECK (target_generation >= 1),
            expected_revision integer NOT NULL CHECK (expected_revision >= 0),
            key varchar(128) NOT NULL,
            payload_hash varchar(64) NOT NULL,
            new_conditions jsonb,
            status text NOT NULL CHECK (status IN (
                'pending', 'intent_confirmed', 'effect_applied',
                'effect_rejected', 'completed', 'rejected')),
            result jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (owner_id, kind, key),
            CHECK ((kind = 'plan.change_conditions') =
                   (new_conditions IS NOT NULL AND expected_revision > 0)),
            CHECK ((status IN ('effect_applied', 'effect_rejected',
                              'completed', 'rejected')) = (result IS NOT NULL))
        )
    """)
    op.execute("""
        CREATE INDEX control_commands_owner_created
            ON control_commands (owner_id, created_at DESC, id DESC)
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
