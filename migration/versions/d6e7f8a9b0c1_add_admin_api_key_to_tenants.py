"""add admin api key to tenants

Revision ID: d6e7f8a9b0c1
Revises: c4d5e6f7a8b9
Create Date: 2026-03-10 00:00:00.000000
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa


revision = "d6e7f8a9b0c1"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("admin_api_key", sa.String(length=255), nullable=True))

    admin_api_key = os.getenv("WEB_ADMIN_KEY", "").strip()
    if admin_api_key:
        op.execute(
            sa.text(
                "UPDATE tenants SET admin_api_key = :admin_api_key "
                "WHERE slug = 'default' AND (admin_api_key IS NULL OR admin_api_key = '')"
            ).bindparams(admin_api_key=admin_api_key)
        )


def downgrade() -> None:
    op.drop_column("tenants", "admin_api_key")