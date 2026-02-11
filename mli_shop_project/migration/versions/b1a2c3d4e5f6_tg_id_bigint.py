"""Use bigint for users.tg_id.

Revision ID: b1a2c3d4e5f6
Revises: 947a937d4251
Create Date: 2026-02-10
"""

from alembic import op
import sqlalchemy as sa


revision = "b1a2c3d4e5f6"
down_revision = "947a937d4251"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "tg_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "tg_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
