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
    # 先以可空方式加列（避免对存量行加 NOT NULL 报错），再回填默认配置，最后收紧为 NOT NULL，
    # 与同表的 memory/rag/tool_policy 等列的 NOT NULL 契约及模型 Mapped[dict] 注解保持一致。
    op.add_column("agent_settings", sa.Column("query_understanding", sa.JSON(), nullable=True))
    op.execute(
        "UPDATE agent_settings SET query_understanding = "
        "'{\"enabled\": true, \"model\": null, \"confidence_threshold\": 0.5, "
        "\"clarify_enabled\": true, \"history_turns\": 4}'::json "
        "WHERE query_understanding IS NULL"
    )
    op.alter_column("agent_settings", "query_understanding", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    op.drop_column("agent_settings", "query_understanding")
