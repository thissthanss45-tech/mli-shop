"""add is_blocked to users

Revision ID: e3f4a1b2c3d4
Revises: d2a5f6b9c1a2
Create Date: 2026-02-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e3f4a1b2c3d4"
down_revision = "d2a5f6b9c1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.alter_column("users", "is_blocked", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "is_blocked")
