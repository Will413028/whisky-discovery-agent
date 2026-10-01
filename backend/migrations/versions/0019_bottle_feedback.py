"""Store explicit favorites separately from tasting feedback."""

from alembic import op

revision = "0019_bottle_feedback"
down_revision = "0018_library_conclusions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE library_bottle_feedback (
            id uuid PRIMARY KEY,
            owner_id uuid NOT NULL REFERENCES users(id),
            generation integer NOT NULL CHECK (generation>=1),
            bottle_version_id uuid NOT NULL,
            revision integer NOT NULL CHECK (revision>=1),
            want_to_explore boolean NOT NULL,
            tasting text NOT NULL CHECK (tasting IN ('not_tasted','liked','disliked')),
            tasting_reason varchar(2000) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (owner_id,generation,bottle_version_id),
            CHECK (tasting<>'not_tasted' OR tasting_reason='')
        );
        CREATE INDEX library_feedback_owner_page
            ON library_bottle_feedback
                (owner_id,generation,updated_at DESC,id DESC);
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
