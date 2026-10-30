"""B1 role policies (additive: one new table; the built-in defaults still apply when no row exists)

Revision ID: c1a0c0de0002
Revises: b1a0c0de0001
"""
import sqlalchemy as sa

from alembic import op

revision = "c1a0c0de0002"
down_revision = "b1a0c0de0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "b1_role_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("strategy", sa.String(16), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("role", "kind", name="uq_b1_role_policy"),
    )


def downgrade() -> None:
    op.drop_table("b1_role_policies")
