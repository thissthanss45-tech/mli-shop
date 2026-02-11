"""Initial migration.

Revision ID: 947a937d4251
Revises: 
Create Date: 2026-02-10
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "947a937d4251"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
	user_role = sa.Enum("client", "staff", "owner", name="userrole")
	order_status = sa.Enum("new", "processing", "completed", "cancelled", name="orderstatus")

	op.create_table(
		"users",
		sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
		sa.Column("tg_id", sa.Integer(), nullable=False),
		sa.Column("username", sa.String(length=255), nullable=True),
		sa.Column("first_name", sa.String(length=255), nullable=True),
		sa.Column("last_name", sa.String(length=255), nullable=True),
		sa.Column("role", user_role, nullable=False, server_default="client"),
		sa.Column("ai_quota", sa.Integer(), nullable=False, server_default="25"),
		sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
		sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
		sa.UniqueConstraint("tg_id"),
	)
	op.create_index("ix_users_tg_id", "users", ["tg_id"], unique=True)

	op.create_table(
		"categories",
		sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
		sa.Column("name", sa.String(length=255), nullable=False),
		sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
		sa.UniqueConstraint("name"),
	)

	op.create_table(
		"brands",
		sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
		sa.Column("name", sa.String(length=255), nullable=False),
		sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
		sa.UniqueConstraint("name"),
	)

	op.create_table(
		"products",
		sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
		sa.Column("title", sa.String(length=500), nullable=False),
		sa.Column("description", sa.Text(), nullable=True),
		sa.Column("purchase_price", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
		sa.Column("sale_price", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
		sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="CASCADE"), nullable=False),
		sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id", ondelete="CASCADE"), nullable=False),
		sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
		sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
	)

	op.create_table(
		"product_stock",
		sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
		sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
		sa.Column("size", sa.String(length=50), nullable=False),
		sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
		sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
		sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
	)

	op.create_table(
		"photos",
		sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
		sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
		sa.Column("file_id", sa.String(length=500), nullable=False),
		sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
	)

	op.create_table(
		"orders",
		sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
		sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
		sa.Column("full_name", sa.String(length=255), nullable=False),
		sa.Column("phone", sa.String(length=50), nullable=False),
		sa.Column("address", sa.Text(), nullable=True),
		sa.Column("total_price", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
		sa.Column("status", order_status, nullable=False, server_default="new"),
		sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
		sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
	)

	op.create_table(
		"order_items",
		sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
		sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
		sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
		sa.Column("size", sa.String(length=50), nullable=False),
		sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
		sa.Column("sale_price", sa.Numeric(10, 2), nullable=False),
		sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
	)

	op.create_table(
		"cart_items",
		sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
		sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
		sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
		sa.Column("size", sa.String(length=50), nullable=False),
		sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
		sa.Column("price_at_add", sa.Numeric(10, 2), nullable=False),
		sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
		sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
	)


def downgrade() -> None:
	op.drop_table("cart_items")
	op.drop_table("order_items")
	op.drop_table("orders")
	op.drop_table("photos")
	op.drop_table("product_stock")
	op.drop_table("products")
	op.drop_table("brands")
	op.drop_table("categories")
	op.drop_index("ix_users_tg_id", table_name="users")
	op.drop_table("users")

	sa.Enum(name="orderstatus").drop(op.get_bind(), checkfirst=True)
	sa.Enum(name="userrole").drop(op.get_bind(), checkfirst=True)
