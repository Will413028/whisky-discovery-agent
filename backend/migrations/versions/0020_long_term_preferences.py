"""Store explicit account preferences separately from exploration conditions."""

from alembic import op

revision = "0020_long_term_preferences"
down_revision = "0019_bottle_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE library_preferences (
            owner_id uuid NOT NULL REFERENCES users(id),
            generation integer NOT NULL CHECK(generation>=1),
            revision integer NOT NULL CHECK(revision>=1),
            preferences jsonb NOT NULL CHECK(
                jsonb_typeof(preferences)='array'
                AND jsonb_array_length(preferences)<=64),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(owner_id,generation)
        );
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
