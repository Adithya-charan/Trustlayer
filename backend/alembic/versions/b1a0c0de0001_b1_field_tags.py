"""B1 field tags (additive: one new table, nothing existing is altered)

Revision ID: b1a0c0de0001
Revises: 9aa71bdbad22
"""
import sqlalchemy as sa

from alembic import op

revision = "b1a0c0de0001"
down_revision = "9aa71bdbad22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "b1_field_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target", sa.String(32), nullable=False),
        sa.Column("table_name", sa.String(64), nullable=False),
        sa.Column("column_name", sa.String(64), nullable=False),
        sa.Column("data_type", sa.String(64), nullable=False, server_default=""),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("tag", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("methods", sa.JSON(), nullable=False),
        sa.Column("match_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rationale", sa.String(200), nullable=False, server_default=""),
        sa.Column("override", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reviewed_by", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("target", "table_name", "column_name", name="uq_b1_field"),
    )


def downgrade() -> None:
    op.drop_table("b1_field_tags")
