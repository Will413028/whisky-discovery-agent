"""Research task snapshots and start acceptance receipts."""

from alembic import op

revision = "0006_research_acceptance"
down_revision = "0005_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE research_tasks (
            id uuid PRIMARY KEY,
            owner_id uuid NOT NULL,
            plan_id uuid NOT NULL,
            generation integer NOT NULL CHECK (generation >= 1),
            conditions_revision integer NOT NULL CHECK (conditions_revision >= 1),
            conditions_schema_version integer NOT NULL
                CHECK (conditions_schema_version = 1),
            conditions jsonb NOT NULL,
            workflow_id text NOT NULL UNIQUE,
            temporal_run_id text,
            thread_id uuid NOT NULL UNIQUE,
            status text NOT NULL CHECK (status IN (
                'acceptance_pending', 'queued', 'researching', 'needs_input',
                'completed', 'failed', 'cancelled', 'superseded')),
            stage text NOT NULL,
            view_version bigint NOT NULL CHECK (view_version >= 1),
            write_allowed boolean NOT NULL,
            question jsonb,
            report_id uuid,
            error jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT research_tasks_owner_unique UNIQUE (id, owner_id),
            CONSTRAINT research_tasks_owned_plan FOREIGN KEY (plan_id, owner_id)
                REFERENCES plans (id, owner_id),
            CONSTRAINT research_tasks_workflow_identity
                CHECK (workflow_id = 'whisky-research-' || id::text),
            CONSTRAINT research_tasks_status_payload CHECK (
                ((status = 'completed') = (report_id IS NOT NULL)) AND
                ((status = 'needs_input') = (question IS NOT NULL)) AND
                ((status = 'failed') = (error IS NOT NULL)))
        )
    """)
    op.execute("""
        CREATE TABLE research_commands (
            id uuid PRIMARY KEY,
            owner_id uuid NOT NULL,
            generation integer NOT NULL CHECK (generation >= 1),
            scope text NOT NULL CHECK (scope = 'research.start'),
            key varchar(128) NOT NULL,
            payload_hash varchar(64) NOT NULL,
            task_id uuid NOT NULL,
            status text NOT NULL CHECK (status IN ('acceptance_pending', 'accepted')),
            result jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT research_commands_key_unique UNIQUE (owner_id, scope, key),
            CONSTRAINT research_commands_owned_task FOREIGN KEY (task_id, owner_id)
                REFERENCES research_tasks (id, owner_id),
            CONSTRAINT research_commands_result CHECK (
                (status = 'accepted') = (result IS NOT NULL))
        )
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
