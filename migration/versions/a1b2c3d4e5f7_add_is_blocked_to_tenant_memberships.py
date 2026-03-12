"""add is_blocked to tenant memberships

Revision ID: a1b2c3d4e5f7
Revises: f9a1b2c3d4e5
Create Date: 2026-03-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f7"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_memberships",
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE tenant_memberships tm
            SET is_blocked = u.is_blocked
            FROM users u
            WHERE u.id = tm.user_id
            """
        )
    )

    op.alter_column("tenant_memberships", "is_blocked", server_default=None)


def downgrade() -> None:
    op.drop_column("tenant_memberships", "is_blocked")
