"""add query_understanding column to agent_settings

Revision ID: b2f1c3a4d5e6
Revises: 877ea8456da8
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "b2f1c3a4d5e6"
down_revision = "877ea8456da8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_settings", sa.Column("query_understanding", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_settings", "query_understanding")
