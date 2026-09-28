"""Persist one versioned human question and its answer receipts per research task."""

from alembic import op

revision = "0009_clarifications"
down_revision = "0008_research_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE clarifications (
            id uuid PRIMARY KEY,
            task_id uuid NOT NULL,
            owner_id uuid NOT NULL,
            generation integer NOT NULL,
            conditions_revision integer NOT NULL,
            waiting_version integer NOT NULL CHECK (waiting_version >= 1),
            prompt text NOT NULL CHECK (length(btrim(prompt)) BETWEEN 1 AND 2000),
            choices jsonb NOT NULL CHECK (
                jsonb_typeof(choices) = 'array'
                AND jsonb_array_length(choices) BETWEEN 2 AND 5),
            status text NOT NULL CHECK
                (status IN ('pending','answered','expired','closed')),
            expires_at timestamptz NOT NULL,
            answer text,
            answer_command_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            answered_at timestamptz,
            UNIQUE (task_id, waiting_version),
            UNIQUE (id, task_id),
            FOREIGN KEY (task_id, owner_id, generation, conditions_revision)
                REFERENCES research_tasks
                    (id, owner_id, generation, conditions_revision),
            CHECK ((status = 'answered') = (answer IS NOT NULL)),
            CHECK ((status = 'answered') = (answer_command_id IS NOT NULL))
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX clarifications_one_pending
            ON clarifications (task_id) WHERE status='pending'
    """)
    op.execute("""
        ALTER TABLE research_tasks ADD COLUMN active_question_id uuid,
            ADD CONSTRAINT research_tasks_active_question
                FOREIGN KEY (active_question_id, id)
                REFERENCES clarifications (id, task_id),
            ADD CONSTRAINT research_tasks_question_pointer
                CHECK ((status='needs_input') = (active_question_id IS NOT NULL))
    """)
    op.execute("""
        ALTER TABLE research_commands
            DROP CONSTRAINT research_commands_scope_check,
            DROP CONSTRAINT research_commands_status_check,
            DROP CONSTRAINT research_commands_result,
            ADD COLUMN question_id uuid REFERENCES clarifications (id),
            ADD COLUMN waiting_version integer,
            ADD CONSTRAINT research_commands_scope CHECK (
                (scope='research.start' AND question_id IS NULL
                    AND waiting_version IS NULL) OR
                (scope='research.answer' AND question_id IS NOT NULL
                    AND waiting_version >= 1)),
            ADD CONSTRAINT research_commands_status_check CHECK
                (status IN ('acceptance_pending','accepted','rejected')),
            ADD CONSTRAINT research_commands_result CHECK
                ((status='acceptance_pending') = (result IS NULL)),
            ADD UNIQUE (id, task_id, owner_id, question_id)
    """)
    op.execute("""
        ALTER TABLE clarifications ADD CONSTRAINT clarifications_answer_receipt
            FOREIGN KEY (answer_command_id, task_id, owner_id, id)
            REFERENCES research_commands (id, task_id, owner_id, question_id)
    """)
    op.execute("""
        CREATE UNIQUE INDEX agent_turns_one_open_per_task
            ON agent_turns (task_id) WHERE outcome IS NULL
    """)
    op.execute("""
        ALTER TABLE research_reports
            ADD COLUMN clarification_id uuid REFERENCES clarifications (id),
            ADD COLUMN selected_version_id uuid,
            ADD COLUMN selected_label text,
            ADD COLUMN selected_item_id uuid,
            ADD CONSTRAINT research_reports_selected_version_pair CHECK (
                (clarification_id IS NULL AND selected_version_id IS NULL
                 AND selected_label IS NULL AND selected_item_id IS NULL)
                OR (clarification_id IS NOT NULL AND selected_version_id IS NOT NULL
                    AND selected_label IS NOT NULL)),
            ADD CONSTRAINT research_reports_selected_current_item
                FOREIGN KEY (catalog_release_id, selected_item_id, selected_version_id)
                REFERENCES catalog_items (release_id, id, bottle_version_id)
    """)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
