"""add tenants and tenant settings

Revision ID: b2c3d4e5f6a7
Revises: f9a1b2c3d4e5
Create Date: 2026-03-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "b2c3d4e5f6a7"
down_revision = "f9a1b2c3d4e5"
branch_labels = None
depends_on = None


def _json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("bot_token", sa.String(length=255), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    op.create_table(
        "tenant_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("locale", sa.String(length=10), nullable=False, server_default="ru"),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/Moscow"),
        sa.Column("currency_code", sa.String(length=8), nullable=False, server_default="RUB"),
        sa.Column("storefront_title", sa.String(length=255), nullable=False),
        sa.Column("support_label", sa.String(length=255), nullable=False, server_default="Поддержка"),
        sa.Column("owner_title", sa.String(length=255), nullable=False, server_default="Владелец"),
        sa.Column("staff_title", sa.String(length=255), nullable=False, server_default="Сотрудник"),
        sa.Column("welcome_text_client", sa.Text(), nullable=True),
        sa.Column("welcome_text_staff", sa.Text(), nullable=True),
        sa.Column("welcome_text_owner", sa.Text(), nullable=True),
        sa.Column("button_labels", _json_type(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("menu_client", _json_type(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("menu_staff", _json_type(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("menu_owner", _json_type(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("ui_theme", _json_type(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("ai_settings", _json_type(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("tenant_id"),
    )

    op.add_column("users", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"], unique=False)
    op.create_foreign_key(
        "fk_users_tenant_id",
        "users",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_tenant_id", "users", type_="foreignkey")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_column("users", "tenant_id")

    op.drop_table("tenant_settings")

    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")