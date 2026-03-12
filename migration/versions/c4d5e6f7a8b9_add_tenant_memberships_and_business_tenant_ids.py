"""add tenant memberships and business tenant ids

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-03-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c4d5e6f7a8b9"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def _ensure_default_tenant() -> int:
    bind = op.get_bind()
    row = bind.execute(sa.text("SELECT id FROM tenants WHERE slug = 'default' LIMIT 1")).fetchone()
    if row:
        return int(row[0])

    tenant_id = bind.execute(
        sa.text(
            """
            INSERT INTO tenants (slug, title, status, created_at, updated_at)
            VALUES ('default', 'Main Store', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """
        )
    ).scalar_one()

    bind.execute(
        sa.text(
            """
            INSERT INTO tenant_settings (
                tenant_id, locale, timezone, currency_code, storefront_title,
                support_label, owner_title, staff_title,
                welcome_text_client, welcome_text_staff, welcome_text_owner,
                button_labels, menu_client, menu_staff, menu_owner, ui_theme, ai_settings,
                created_at, updated_at
            ) VALUES (
                :tenant_id, 'ru', 'Europe/Moscow', 'RUB', 'Main Store',
                'Поддержка', 'Владелец', 'Сотрудник',
                'Привет! Выбери действие:', 'Привет! Твой рабочий терминал готов.', 'Привет! Выбери действие:',
                '{}', '[]', '[]', '[]', '{}', '{}',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        ),
        {"tenant_id": int(tenant_id)},
    )
    return int(tenant_id)


def upgrade() -> None:
    tenant_id = _ensure_default_tenant()
    existing_user_role = postgresql.ENUM("client", "staff", "owner", name="userrole", create_type=False)

    op.create_table(
        "tenant_memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", existing_user_role, nullable=False, server_default="client"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
    )
    op.create_index("ix_tenant_memberships_tenant_id", "tenant_memberships", ["tenant_id"], unique=False)
    op.create_index("ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"], unique=False)

    target_tables = [
        "categories",
        "brands",
        "products",
        "product_stock",
        "photos",
        "orders",
        "order_items",
        "cart_items",
        "stock_movements",
        "ai_chat_logs",
    ]
    for table_name in target_tables:
        op.add_column(table_name, sa.Column("tenant_id", sa.Integer(), nullable=True))
        op.create_index(f"ix_{table_name}_tenant_id", table_name, ["tenant_id"], unique=False)
        op.create_foreign_key(
            f"fk_{table_name}_tenant_id",
            table_name,
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="CASCADE",
        )

    bind = op.get_bind()

    bind.execute(sa.text("UPDATE users SET tenant_id = :tenant_id WHERE tenant_id IS NULL"), {"tenant_id": tenant_id})
    for table_name in target_tables:
        bind.execute(sa.text(f"UPDATE {table_name} SET tenant_id = :tenant_id WHERE tenant_id IS NULL"), {"tenant_id": tenant_id})

    bind.execute(
        sa.text(
            """
            INSERT INTO tenant_memberships (tenant_id, user_id, role, created_at, updated_at)
            SELECT :tenant_id, id, role, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM users
            WHERE NOT EXISTS (
                SELECT 1 FROM tenant_memberships tm WHERE tm.tenant_id = :tenant_id AND tm.user_id = users.id
            )
            """
        ),
        {"tenant_id": tenant_id},
    )

    bind.execute(sa.text("ALTER TABLE categories DROP CONSTRAINT IF EXISTS categories_name_key"))
    bind.execute(sa.text("ALTER TABLE brands DROP CONSTRAINT IF EXISTS brands_name_key"))
    bind.execute(sa.text("ALTER TABLE products DROP CONSTRAINT IF EXISTS products_sku_key"))
    op.create_unique_constraint("uq_categories_tenant_name", "categories", ["tenant_id", "name"])
    op.create_unique_constraint("uq_brands_tenant_name", "brands", ["tenant_id", "name"])
    op.create_unique_constraint("uq_products_tenant_sku", "products", ["tenant_id", "sku"])


def downgrade() -> None:
    op.drop_constraint("uq_products_tenant_sku", "products", type_="unique")
    op.drop_constraint("uq_brands_tenant_name", "brands", type_="unique")
    op.drop_constraint("uq_categories_tenant_name", "categories", type_="unique")

    target_tables = [
        "categories",
        "brands",
        "products",
        "product_stock",
        "photos",
        "orders",
        "order_items",
        "cart_items",
        "stock_movements",
        "ai_chat_logs",
    ]
    for table_name in reversed(target_tables):
        op.drop_constraint(f"fk_{table_name}_tenant_id", table_name, type_="foreignkey")
        op.drop_index(f"ix_{table_name}_tenant_id", table_name=table_name)
        op.drop_column(table_name, "tenant_id")

    op.drop_index("ix_tenant_memberships_user_id", table_name="tenant_memberships")
    op.drop_index("ix_tenant_memberships_tenant_id", table_name="tenant_memberships")
    op.drop_table("tenant_memberships")