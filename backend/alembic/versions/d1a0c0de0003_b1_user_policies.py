"""B1 per-user masking policies (additive: one new table; role policy and the built-in defaults still apply when no row exists)

Revision ID: d1a0c0de0003
Revises: c1a0c0de0002
"""
import sqlalchemy as sa

from alembic import op

revision = "d1a0c0de0003"
down_revision = "c1a0c0de0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "b1_user_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, index=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("strategy", sa.String(16), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username", "kind", name="uq_b1_user_policy"),
    )


def downgrade() -> None:
    op.drop_table("b1_user_policies")
