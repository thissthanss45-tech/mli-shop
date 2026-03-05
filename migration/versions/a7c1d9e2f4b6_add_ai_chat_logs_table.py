"""add ai chat logs table

Revision ID: a7c1d9e2f4b6
Revises: f4b7c8d9e0f1
Create Date: 2026-02-24 18:45:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7c1d9e2f4b6"
down_revision = "f4b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_chat_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_chat_logs_user_tg_id", "ai_chat_logs", ["user_tg_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_chat_logs_user_tg_id", table_name="ai_chat_logs")
    op.drop_table("ai_chat_logs")
