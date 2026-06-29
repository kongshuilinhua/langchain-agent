"""add uploads.storage_key (object storage reference)

Revision ID: 0002_upload_storage_key
Revises: 0001_baseline
Create Date: 2026-06-27

给 uploads 增加 storage_key 列：非空表示文件字节存在对象库（MinIO/OSS），
DB 不再背 base64 大列。server_default='' 让存量行平滑获得非空值。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_upload_storage_key"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("uploads", sa.Column("storage_key", sa.String(length=255), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("uploads", "storage_key")
