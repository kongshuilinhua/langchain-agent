"""Add query_understanding column to agent_settings.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_settings",
        sa.Column("query_understanding", sa.JSON(), nullable=False,
                  server_default=sa.text("'{}'")),
    )
    # Fill existing rows with default JSON object (no ::json cast needed for MySQL)
    op.execute(
        "UPDATE agent_settings SET query_understanding = "
        "'{\"enabled\": true, \"model\": null, \"confidence_threshold\": 0.5, "
        "\"clarify_enabled\": true, \"history_turns\": 4}' "
        "WHERE query_understanding IS NULL"
    )


def downgrade() -> None:
    op.drop_column("agent_settings", "query_understanding")
