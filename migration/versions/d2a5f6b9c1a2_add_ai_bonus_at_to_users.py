"""add ai bonus timestamp

Revision ID: d2a5f6b9c1a2
Revises: c7e1f1a8d9e0
Create Date: 2026-02-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d2a5f6b9c1a2"
down_revision = "c7e1f1a8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("ai_bonus_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "ai_bonus_at")
