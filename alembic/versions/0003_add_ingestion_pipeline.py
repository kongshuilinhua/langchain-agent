"""Add knowledge_parent_chunks table and ingestion_log column.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("knowledge_documents", sa.Column("ingestion_log", sa.JSON(), nullable=True))
    op.create_table(
        "knowledge_parent_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_base_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.String(length=120), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "parent_id", name="uq_parent_chunk_doc_parent"),
    )
    op.create_index("ix_knowledge_parent_chunks_workspace_id", "knowledge_parent_chunks", ["workspace_id"])
    op.create_index("ix_knowledge_parent_chunks_knowledge_base_id", "knowledge_parent_chunks", ["knowledge_base_id"])
    op.create_index("ix_knowledge_parent_chunks_document_id", "knowledge_parent_chunks", ["document_id"])
    op.create_index("ix_knowledge_parent_chunks_parent_id", "knowledge_parent_chunks", ["parent_id"])


def downgrade() -> None:
    op.drop_table("knowledge_parent_chunks")
    op.drop_column("knowledge_documents", "ingestion_log")
