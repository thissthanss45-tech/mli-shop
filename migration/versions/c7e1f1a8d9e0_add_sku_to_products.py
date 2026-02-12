"""add sku to products

Revision ID: c7e1f1a8d9e0
Revises: b1a2c3d4e5f6
Create Date: 2026-02-12
"""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c7e1f1a8d9e0"
down_revision = "b1a2c3d4e5f6"
branch_labels = None
depends_on = None


def _normalize_sku_prefix(brand_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", (brand_name or "").upper())
    if not cleaned:
        return "SKU"
    if len(cleaned) < 3:
        cleaned = (cleaned + "XXX")[:3]
    return cleaned[:3]


def _build_sku(brand_name: str, product_id: int) -> str:
    prefix = _normalize_sku_prefix(brand_name)
    return f"{prefix}-{product_id:06d}"


def upgrade() -> None:
    op.add_column("products", sa.Column("sku", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_products_sku", "products", ["sku"])

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT p.id, b.name "
            "FROM products p "
            "JOIN brands b ON b.id = p.brand_id"
        )
    ).fetchall()

    for product_id, brand_name in rows:
        sku = _build_sku(brand_name, product_id)
        bind.execute(
            sa.text("UPDATE products SET sku = :sku WHERE id = :id"),
            {"sku": sku, "id": product_id},
        )

    op.alter_column("products", "sku", nullable=False)


def downgrade() -> None:
    op.drop_constraint("uq_products_sku", "products", type_="unique")
    op.drop_column("products", "sku")
