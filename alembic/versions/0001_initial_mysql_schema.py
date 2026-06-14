"""MySQL initial schema — baseline for all future migrations.

Tables are created by Base.metadata.create_all() in core.db.session.init_db().
This revision serves as the Alembic version anchor for MySQL deployments.

Revision ID: 0001
Revises: None
Create Date: 2026-06-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables from the SQLAlchemy metadata."""
    # Tables are managed by core.db.session.init_db() -> Base.metadata.create_all().
    # This migration ensures the alembic_version table is stamped.
    pass


def downgrade() -> None:
    """Drop all tables."""
    # ⚠️  This is destructive. Only use in development.
    pass
