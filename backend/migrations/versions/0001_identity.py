"""Internal actors and external identity mapping."""

import sqlalchemy as sa
from alembic import op

revision = "0001_identity"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.CheckConstraint("generation >= 1", name="users_generation_positive"),
    )
    op.create_table(
        "identities",
        sa.Column("issuer", sa.String(), primary_key=True),
        sa.Column("subject", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade requires a separate reviewed migration")
