"""Transactionally reserve model and reader attempts across worker restarts."""

from alembic import op

revision = "0011_research_usage"
down_revision = "0010_control_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE research_usage_limiter (
            id smallint PRIMARY KEY CHECK (id = 1)
        )
    """)
    op.execute("INSERT INTO research_usage_limiter (id) VALUES (1)")
    op.execute("""
        CREATE TABLE research_usage_days (
            day_utc date PRIMARY KEY,
            reserved_neurons integer NOT NULL DEFAULT 0
                CHECK (reserved_neurons >= 0)
        )
    """)
    op.execute("""
        CREATE TABLE research_usage_attempts (
            id uuid PRIMARY KEY,
            task_id uuid NOT NULL REFERENCES research_tasks (id)
                ON DELETE CASCADE,
            owner_id uuid NOT NULL,
            activity_id text NOT NULL,
            attempt integer NOT NULL CHECK (attempt >= 1),
            kind text NOT NULL CHECK (kind IN ('model', 'reader')),
            model_name text,
            status text NOT NULL CHECK (status IN ('active', 'completed', 'unknown')),
            day_utc date NOT NULL REFERENCES research_usage_days (day_utc),
            reserved_input_tokens integer NOT NULL
                CHECK (reserved_input_tokens >= 0),
            reserved_output_tokens integer NOT NULL
                CHECK (reserved_output_tokens >= 0),
            reserved_neurons integer NOT NULL CHECK (reserved_neurons >= 0),
            actual_input_tokens integer,
            actual_output_tokens integer,
            latency_ms integer,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            UNIQUE (task_id, kind, activity_id, attempt),
            CHECK ((kind = 'model') = (model_name IS NOT NULL)),
            CHECK ((status = 'active') = (finished_at IS NULL))
        )
    """)
    op.execute("""
        CREATE INDEX research_usage_active_owner
            ON research_usage_attempts (owner_id, task_id)
            WHERE status = 'active'
    """)
    op.execute("""
        CREATE INDEX research_usage_task_kind
            ON research_usage_attempts (task_id, kind)
    """)
    op.execute("""
        CREATE TABLE research_source_observations (
            id uuid PRIMARY KEY,
            task_id uuid NOT NULL,
            owner_id uuid NOT NULL,
            generation integer NOT NULL,
            conditions_revision integer NOT NULL,
            activity_id text NOT NULL,
            release_id uuid NOT NULL,
            bottle_version_id uuid NOT NULL,
            evidence_id uuid NOT NULL,
            status text NOT NULL CHECK (status IN ('ok', 'unavailable')),
            review_status text NOT NULL DEFAULT 'unreviewed'
                CHECK (review_status = 'unreviewed'),
            error_code text,
            visible_text text,
            effective_url text,
            content_sha256 char(64),
            source_checked_on date NOT NULL,
            observed_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (task_id, activity_id),
            FOREIGN KEY (task_id, owner_id, generation, conditions_revision)
                REFERENCES research_tasks
                    (id, owner_id, generation, conditions_revision),
            FOREIGN KEY (release_id, evidence_id, bottle_version_id)
                REFERENCES catalog_evidence (release_id, id, bottle_version_id),
            CHECK (
                (status='ok' AND error_code IS NULL
                    AND visible_text IS NOT NULL AND content_sha256 IS NOT NULL
                    AND effective_url IS NOT NULL)
                OR
                (status='unavailable' AND error_code IS NOT NULL
                    AND visible_text IS NULL AND content_sha256 IS NULL
                    AND effective_url IS NULL)
            ),
            CHECK (visible_text IS NULL OR length(visible_text) <= 2000),
            CHECK (effective_url IS NULL OR length(effective_url) <= 2048)
        )
    """)
    op.execute("""
        CREATE INDEX research_source_observations_owner_task
            ON research_source_observations (owner_id, task_id)
    """)
    op.execute("""
        CREATE TABLE research_report_source_observations (
            report_id uuid NOT NULL REFERENCES research_reports (id)
                ON DELETE CASCADE,
            ordinal integer NOT NULL CHECK (ordinal >= 0),
            observation_id uuid NOT NULL
                REFERENCES research_source_observations (id),
            PRIMARY KEY (report_id, ordinal),
            UNIQUE (report_id, observation_id)
        )
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
