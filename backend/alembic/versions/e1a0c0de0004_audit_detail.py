"""Structured audit detail (additive: one nullable JSON column on audit_events; existing rows keep NULL and are explained from their reason text)

Revision ID: e1a0c0de0004
Revises: d1a0c0de0003
"""
import sqlalchemy as sa

from alembic import op

revision = "e1a0c0de0004"
down_revision = "d1a0c0de0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("detail", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_events", "detail")
