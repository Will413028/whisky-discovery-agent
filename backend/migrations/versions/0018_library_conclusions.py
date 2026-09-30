"""Persist user choices without treating them as reviewed catalog facts."""

from alembic import op

revision = "0018_library_conclusions"
down_revision = "0017_restart_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE library_conclusions (
            id uuid PRIMARY KEY,
            owner_id uuid NOT NULL REFERENCES users (id),
            generation integer NOT NULL CHECK (generation>=1),
            plan_id uuid NOT NULL,
            task_id uuid NOT NULL,
            report_id uuid NOT NULL,
            conditions_revision integer NOT NULL CHECK (conditions_revision>=1),
            conditions jsonb NOT NULL,
            catalog_release_id uuid,
            evaluated_on date NOT NULL,
            revision integer NOT NULL DEFAULT 1 CHECK (revision>=1),
            content jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            deleted_at timestamptz,
            UNIQUE (id,owner_id),
            FOREIGN KEY (plan_id,owner_id) REFERENCES plans (id,owner_id),
            FOREIGN KEY (report_id,task_id,owner_id)
                REFERENCES research_reports (id,task_id,owner_id),
            CHECK (conditions @> '{"schema_version": 1}'::jsonb),
            CHECK (content @> '{"schemaVersion": 1}'::jsonb)
        );
        CREATE INDEX library_conclusions_owner_page
            ON library_conclusions
                (owner_id,generation,plan_id,updated_at DESC,id DESC)
            WHERE deleted_at IS NULL;
        CREATE TABLE library_commands (
            id uuid PRIMARY KEY,
            owner_id uuid NOT NULL REFERENCES users (id),
            generation integer NOT NULL CHECK (generation>=1),
            scope text NOT NULL,
            key varchar(128) NOT NULL,
            payload_hash varchar(64) NOT NULL,
            target_id uuid NOT NULL,
            response jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (owner_id,generation,scope,key)
        );
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
