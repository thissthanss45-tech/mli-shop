"""add stock movements table

Revision ID: f4b7c8d9e0f1
Revises: e3f4a1b2c3d4
Create Date: 2026-02-16 12:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f4b7c8d9e0f1"
down_revision = "e3f4a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'movementdirection') THEN
                CREATE TYPE movementdirection AS ENUM ('in', 'out');
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'movementoperation') THEN
                CREATE TYPE movementoperation AS ENUM ('sale', 'manual_add', 'manual_write_off', 'return', 'correction');
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_movements (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            order_id INTEGER NULL REFERENCES orders(id) ON DELETE SET NULL,
            size VARCHAR(50) NOT NULL,
            quantity INTEGER NOT NULL,
            stock_before INTEGER NOT NULL,
            stock_after INTEGER NOT NULL,
            direction movementdirection NOT NULL,
            operation_type movementoperation NOT NULL,
            unit_purchase_price NUMERIC(10, 2) NULL,
            unit_sale_price NUMERIC(10, 2) NULL,
            note TEXT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_movements_created_at ON stock_movements (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_movements_product_id ON stock_movements (product_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_movements_order_id ON stock_movements (order_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_stock_movements_order_id")
    op.execute("DROP INDEX IF EXISTS ix_stock_movements_product_id")
    op.execute("DROP INDEX IF EXISTS ix_stock_movements_created_at")
    op.execute("DROP TABLE IF EXISTS stock_movements")

    op.execute("DROP TYPE IF EXISTS movementoperation")
    op.execute("DROP TYPE IF EXISTS movementdirection")
