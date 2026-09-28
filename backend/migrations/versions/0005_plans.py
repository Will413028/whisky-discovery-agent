"""Owned exploration plans and atomic creation receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005_plans"
down_revision = "0004_catalog_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("conditions_revision", sa.Integer(), nullable=False),
        sa.Column("conditions_schema_version", sa.Integer(), nullable=False),
        sa.Column("conditions", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("id", "owner_id", name="plans_id_owner_unique"),
        sa.CheckConstraint(
            "generation >= 1 AND conditions_revision >= 1",
            name="plans_versions_positive",
        ),
        sa.CheckConstraint(
            "conditions_schema_version = 1", name="plans_schema_supported"
        ),
    )
    op.create_index("plans_owner_updated", "plans", ["owner_id", "updated_at", "id"])
    op.create_table(
        "discovery_commands",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(80), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "owner_id", "scope", "key", name="discovery_commands_key_unique"
        ),
        sa.CheckConstraint("scope = 'plans.create'", name="discovery_commands_scope"),
        sa.CheckConstraint("status = 'completed'", name="discovery_commands_status"),
        sa.ForeignKeyConstraint(
            ["target_id", "owner_id"],
            ["plans.id", "plans.owner_id"],
            name="discovery_commands_owned_target",
            deferrable=True,
            initially="DEFERRED",
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
