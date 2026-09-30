"""Keep V4 comparison evidence beside the frozen V1 report artifact."""

from alembic import op

revision = "0015_report_comparisons"
down_revision = "0014_preference_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE research_report_comparisons (
            report_id uuid PRIMARY KEY,
            task_id uuid NOT NULL,
            owner_id uuid NOT NULL,
            schema_version integer NOT NULL CHECK (schema_version = 4),
            content jsonb NOT NULL
                CHECK (jsonb_typeof(content) = 'object')
                CHECK (content ? 'schema_version' AND content ? 'candidates')
                CHECK (content->>'schema_version' = '4')
                CHECK (jsonb_typeof(content->'candidates') = 'array')
                CHECK (jsonb_array_length(content->'candidates') BETWEEN 0 AND 3),
            FOREIGN KEY (report_id,task_id,owner_id)
                REFERENCES research_reports (id,task_id,owner_id)
        )
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
