"""harden stock constraints and reporting indexes

Revision ID: f9a1b2c3d4e5
Revises: a7c1d9e2f4b6
Create Date: 2026-03-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f9a1b2c3d4e5"
down_revision = "a7c1d9e2f4b6"
branch_labels = None
depends_on = None


def _cleanup_duplicate_stock_rows() -> None:
    bind = op.get_bind()
    duplicate_rows = bind.execute(
        sa.text(
            """
            SELECT product_id, size, SUM(quantity) AS total_qty, MIN(id) AS keep_id
            FROM product_stock
            GROUP BY product_id, size
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()

    for product_id, size, total_qty, keep_id in duplicate_rows:
        normalized_qty = max(int(total_qty or 0), 0)
        bind.execute(
            sa.text(
                """
                UPDATE product_stock
                SET quantity = :quantity
                WHERE id = :keep_id
                """
            ),
            {"quantity": normalized_qty, "keep_id": keep_id},
        )
        bind.execute(
            sa.text(
                """
                DELETE FROM product_stock
                WHERE product_id = :product_id
                  AND size = :size
                  AND id <> :keep_id
                """
            ),
            {
                "product_id": product_id,
                "size": size,
                "keep_id": keep_id,
            },
        )


def _normalize_negative_quantities() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE product_stock SET quantity = 0 WHERE quantity < 0"))
    bind.execute(sa.text("UPDATE cart_items SET quantity = 0 WHERE quantity < 0"))
    bind.execute(sa.text("UPDATE order_items SET quantity = 0 WHERE quantity < 0"))


def _create_index_if_not_exists(index_name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {idx.get("name") for idx in inspector.get_indexes(table_name)}
    if index_name in existing_indexes:
        return
    op.create_index(index_name, table_name, columns, unique=False)


def upgrade() -> None:
    _cleanup_duplicate_stock_rows()
    _normalize_negative_quantities()

    op.create_unique_constraint(
        "uq_product_stock_product_id_size",
        "product_stock",
        ["product_id", "size"],
    )

    op.create_check_constraint(
        "ck_product_stock_quantity_non_negative",
        "product_stock",
        "quantity >= 0",
    )
    op.create_check_constraint(
        "ck_cart_items_quantity_non_negative",
        "cart_items",
        "quantity >= 0",
    )
    op.create_check_constraint(
        "ck_order_items_quantity_non_negative",
        "order_items",
        "quantity >= 0",
    )

    _create_index_if_not_exists("ix_orders_created_at", "orders", ["created_at"])
    _create_index_if_not_exists("ix_orders_status_created_at", "orders", ["status", "created_at"])
    _create_index_if_not_exists("ix_order_items_order_id", "order_items", ["order_id"])
    _create_index_if_not_exists("ix_stock_movements_created_at", "stock_movements", ["created_at"])
    _create_index_if_not_exists("ix_stock_movements_product_created_at", "stock_movements", ["product_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_stock_movements_product_created_at", table_name="stock_movements")
    op.drop_index("ix_stock_movements_created_at", table_name="stock_movements")
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_index("ix_orders_status_created_at", table_name="orders")
    op.drop_index("ix_orders_created_at", table_name="orders")

    op.drop_constraint("ck_order_items_quantity_non_negative", "order_items", type_="check")
    op.drop_constraint("ck_cart_items_quantity_non_negative", "cart_items", type_="check")
    op.drop_constraint("ck_product_stock_quantity_non_negative", "product_stock", type_="check")

    op.drop_constraint("uq_product_stock_product_id_size", "product_stock", type_="unique")
