"""Store final reports and source references beside their task projection."""

from alembic import op

revision = "0008_research_reports"
down_revision = "0007_agent_turns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE research_tasks ADD CONSTRAINT research_tasks_report_fence_key
            UNIQUE (id, owner_id, generation, conditions_revision)
    """)
    op.execute("""
        CREATE TABLE research_reports (
            id uuid PRIMARY KEY,
            task_id uuid NOT NULL UNIQUE,
            owner_id uuid NOT NULL,
            generation integer NOT NULL,
            conditions_revision integer NOT NULL,
            artifact_key varchar(128) NOT NULL,
            catalog_release_id uuid REFERENCES catalog_releases (id),
            evaluated_on date NOT NULL,
            policy_version varchar(128) NOT NULL,
            prompt_version varchar(128) NOT NULL,
            model_version varchar(128) NOT NULL,
            schema_version integer NOT NULL CHECK (schema_version = 1),
            content jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (task_id, artifact_key),
            UNIQUE (id, task_id, owner_id),
            FOREIGN KEY (task_id, owner_id, generation, conditions_revision)
                REFERENCES research_tasks
                    (id, owner_id, generation, conditions_revision)
        )
    """)
    op.execute("""
        CREATE TABLE research_report_candidates (
            report_id uuid NOT NULL REFERENCES research_reports (id),
            ordinal smallint NOT NULL CHECK (ordinal BETWEEN 0 AND 2),
            release_id uuid NOT NULL,
            item_id uuid NOT NULL,
            bottle_version_id uuid NOT NULL,
            reason text NOT NULL CHECK (length(btrim(reason)) > 0),
            PRIMARY KEY (report_id, ordinal),
            UNIQUE (report_id, release_id, item_id),
            UNIQUE (report_id, ordinal, release_id, item_id, bottle_version_id),
            FOREIGN KEY (release_id, item_id, bottle_version_id)
                REFERENCES catalog_items (release_id, id, bottle_version_id)
        )
    """)
    op.execute("""
        CREATE TABLE research_report_claims (
            report_id uuid NOT NULL,
            ordinal smallint NOT NULL,
            claim_ordinal smallint NOT NULL,
            release_id uuid NOT NULL,
            item_id uuid NOT NULL,
            bottle_version_id uuid NOT NULL,
            kind varchar NOT NULL CHECK (kind IN ('fact', 'tag')),
            key varchar NOT NULL,
            value text NOT NULL,
            PRIMARY KEY (report_id, ordinal, claim_ordinal),
            UNIQUE (report_id, ordinal, claim_ordinal,
                    release_id, item_id, bottle_version_id, kind, key),
            FOREIGN KEY (report_id, ordinal, release_id, item_id, bottle_version_id)
                REFERENCES research_report_candidates
                    (report_id, ordinal, release_id, item_id, bottle_version_id),
            FOREIGN KEY (release_id, item_id, kind, key)
                REFERENCES catalog_claims (release_id, item_id, kind, key)
        )
    """)
    op.execute("""
        CREATE TABLE research_report_citations (
            report_id uuid NOT NULL,
            ordinal smallint NOT NULL,
            claim_ordinal smallint NOT NULL,
            release_id uuid NOT NULL,
            item_id uuid NOT NULL,
            bottle_version_id uuid NOT NULL,
            kind varchar NOT NULL,
            key varchar NOT NULL,
            evidence_id uuid NOT NULL,
            PRIMARY KEY (report_id, ordinal, claim_ordinal, evidence_id),
            FOREIGN KEY (report_id, ordinal, claim_ordinal,
                         release_id, item_id, bottle_version_id, kind, key)
                REFERENCES research_report_claims
                    (report_id, ordinal, claim_ordinal,
                     release_id, item_id, bottle_version_id, kind, key),
            FOREIGN KEY (release_id, item_id, kind, key, evidence_id)
                REFERENCES catalog_citations
                    (release_id, item_id, kind, key, evidence_id)
        )
    """)
    op.execute("""
        ALTER TABLE catalog_prices ADD CONSTRAINT catalog_prices_report_ref
            UNIQUE (release_id, id, item_id, bottle_version_id)
    """)
    op.execute("""
        CREATE TABLE research_report_prices (
            report_id uuid NOT NULL,
            ordinal smallint NOT NULL,
            release_id uuid NOT NULL,
            item_id uuid NOT NULL,
            bottle_version_id uuid NOT NULL,
            price_id uuid NOT NULL,
            PRIMARY KEY (report_id, ordinal, price_id),
            FOREIGN KEY (report_id, ordinal, release_id, item_id, bottle_version_id)
                REFERENCES research_report_candidates
                    (report_id, ordinal, release_id, item_id, bottle_version_id),
            FOREIGN KEY (release_id, price_id, item_id, bottle_version_id)
                REFERENCES catalog_prices
                    (release_id, id, item_id, bottle_version_id)
        )
    """)
    op.execute("""
        ALTER TABLE research_tasks ADD CONSTRAINT research_tasks_saved_report
            FOREIGN KEY (report_id, id, owner_id)
                REFERENCES research_reports (id, task_id, owner_id)
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
