"""add media_type to product media

Revision ID: c9d8e7f6a5b4
Revises: a1b2c3d4e5f7
Create Date: 2026-03-11 08:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c9d8e7f6a5b4"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "photos",
        sa.Column("media_type", sa.String(length=16), nullable=False, server_default="photo"),
    )


def downgrade() -> None:
    op.drop_column("photos", "media_type")