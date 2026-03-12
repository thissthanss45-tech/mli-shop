from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")
os.environ.setdefault("WEB_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("CORS_ORIGINS", "https://example.com")
os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///test_reset_placeholder.db")

from database.db_manager import Base
from database.maintenance import reset_database_data
from models import AIChatLog, Brand, CartItem, Category, Order, OrderItem, Product, ProductStock, StockMovement, User
from utils.tenants import ensure_default_tenant, ensure_tenant_membership


async def _create_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _drop_engine(engine) -> None:
    await engine.dispose()


async def _seed_all(maker: async_sessionmaker[AsyncSession]) -> None:
    async with maker() as session:
        tenant = await ensure_default_tenant(session)
        user = User(tg_id=1001, username="owner", role="owner", ai_quota=25, tenant_id=tenant.id)
        category = Category(name="Shoes", tenant_id=tenant.id)
        brand = Brand(name="Nike", tenant_id=tenant.id)
        session.add_all([user, category, brand])
        await session.flush()
        await ensure_tenant_membership(session, user, tenant.id, "owner")

        product = Product(
            tenant_id=tenant.id,
            sku="NIK-000001",
            title="Air Max",
            description="Test",
            purchase_price=Decimal("100.00"),
            sale_price=Decimal("150.00"),
            category_id=category.id,
            brand_id=brand.id,
        )
        session.add(product)
        await session.flush()

        stock = ProductStock(tenant_id=tenant.id, product_id=product.id, size="42", quantity=5)
        cart_item = CartItem(
            tenant_id=tenant.id,
            user_id=user.id,
            product_id=product.id,
            size="42",
            quantity=1,
            price_at_add=Decimal("150.00"),
        )
        order = Order(
            tenant_id=tenant.id,
            user_id=user.id,
            full_name="Test User",
            phone="+70000000000",
            address="Test address",
            total_price=Decimal("150.00"),
            status="new",
        )
        ai_log = AIChatLog(tenant_id=tenant.id, user_tg_id=user.tg_id, role="user", content="Hello")

        session.add_all([stock, cart_item, order, ai_log])
        await session.flush()

        order_item = OrderItem(
            tenant_id=tenant.id,
            order_id=order.id,
            product_id=product.id,
            size="42",
            quantity=1,
            sale_price=Decimal("150.00"),
        )
        movement = StockMovement(
            tenant_id=tenant.id,
            product_id=product.id,
            order_id=order.id,
            size="42",
            quantity=1,
            stock_before=5,
            stock_after=4,
            direction="out",
            operation_type="sale",
            unit_purchase_price=Decimal("100.00"),
            unit_sale_price=Decimal("150.00"),
            note="Seed movement",
        )
        session.add_all([order_item, movement])
        await session.commit()


async def _collect_counts(maker: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with maker() as session:
        models = {
            "users": User,
            "categories": Category,
            "brands": Brand,
            "products": Product,
            "product_stock": ProductStock,
            "cart_items": CartItem,
            "orders": Order,
            "order_items": OrderItem,
            "stock_movements": StockMovement,
            "ai_chat_logs": AIChatLog,
        }
        counts: dict[str, int] = {}
        for name, model in models.items():
            result = await session.execute(select(func.count()).select_from(model))
            counts[name] = int(result.scalar_one())
        return counts


class DatabaseResetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmp_dir.name, "reset_test.db")
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            poolclass=NullPool,
        )
        self.maker = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        asyncio.run(_create_schema(self.engine))

    def tearDown(self) -> None:
        asyncio.run(_drop_engine(self.engine))
        self._tmp_dir.cleanup()

    def test_reset_database_clears_all_business_tables(self) -> None:
        asyncio.run(_seed_all(self.maker))
        counts_before = asyncio.run(_collect_counts(self.maker))
        self.assertTrue(any(value > 0 for value in counts_before.values()))

        truncated_tables = asyncio.run(reset_database_data(self.engine))
        counts_after = asyncio.run(_collect_counts(self.maker))

        self.assertGreaterEqual(truncated_tables, len(counts_after))
        self.assertTrue(all(value == 0 for value in counts_after.values()))


if __name__ == "__main__":
    unittest.main(verbosity=2)