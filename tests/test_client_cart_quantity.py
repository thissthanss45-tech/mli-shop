from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")
os.environ.setdefault("WEB_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("CORS_ORIGINS", "https://example.com")
os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///test_client_cart_quantity_placeholder.db")

from database.catalog_repo import CatalogRepo  # noqa: E402
from database.db_manager import Base  # noqa: E402
from database.orders_repo import OrdersRepo  # noqa: E402
from handlers import ai as ai_handlers  # noqa: E402
from handlers import client as client_handlers  # noqa: E402
from models import Tenant, User, UserRole  # noqa: E402
from utils.tenants import ensure_default_tenant, ensure_tenant_membership  # noqa: E402


async def _create_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class FakeState:
    def __init__(self, data: dict | None = None) -> None:
        self._data = dict(data or {})
        self.clear = AsyncMock(side_effect=self._clear)
        self.set_state = AsyncMock()

    async def _clear(self):
        self._data.clear()

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)


class FakeMessage:
    def __init__(self, text: str, user_id: int = 5010) -> None:
        self.text = text
        self.chat = SimpleNamespace(id=user_id)
        self.from_user = SimpleNamespace(id=user_id, username="tester", first_name="Test", last_name="User")
        self.answer = AsyncMock()
        self.delete = AsyncMock()


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage, user_id: int = 5010) -> None:
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(id=user_id, username="tester", first_name="Test")
        self.answer = AsyncMock()


class ClientCartQuantityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmp_dir.name, "client_cart_quantity.db")
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            poolclass=NullPool,
        )
        self.maker = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        await _create_schema(self.engine)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self._tmp_dir.cleanup()

    async def _seed_runtime_product(self, session: AsyncSession, quantity: int = 5) -> tuple[Tenant, User, object]:
        tenant = Tenant(slug="flowers-boutique", title="Flowers Boutique", status="active", bot_token=os.environ["BOT_TOKEN"])
        session.add(tenant)
        await session.flush()
        await ensure_default_tenant(session)

        user = User(tg_id=5010, tenant_id=tenant.id, role=UserRole.CLIENT.value, ai_quota=0)
        session.add(user)
        await session.flush()
        membership = await ensure_tenant_membership(session, user, tenant.id, UserRole.CLIENT.value)
        membership.role = UserRole.CLIENT.value

        repo = CatalogRepo(session, tenant_id=tenant.id)
        category = await repo.get_or_create_category("Розы")
        brand = await repo.get_or_create_brand("Rose Studio")
        product = await repo.create_product(
            title="Роза алая",
            purchase_price=100,
            sale_price=200,
            category=category,
            brand=brand,
        )
        await repo.add_stock(product, "шт", quantity)
        await session.commit()
        loaded = await repo.get_product_with_details(product.id)
        return tenant, user, loaded

    async def test_client_can_add_multiple_items_to_cart(self) -> None:
        async with self.maker() as session:
            tenant, user, product = await self._seed_runtime_product(session, quantity=7)
            state = FakeState({"product_id": product.id})

            size_message = FakeMessage("шт", user_id=user.tg_id)
            await client_handlers.process_size_input(size_message, state, session)
            self.assertEqual((await state.get_data())["selected_size"], "шт")

            quantity_message = FakeMessage("3", user_id=user.tg_id)
            await client_handlers.process_quantity_input(quantity_message, state, session)

            orders_repo = OrdersRepo(session, tenant_id=tenant.id)
            cart_items = await orders_repo.list_cart_items(user)
            self.assertEqual(len(cart_items), 1)
            self.assertEqual(cart_items[0].quantity, 3)
            self.assertEqual(cart_items[0].size, "шт")
            first_answer = quantity_message.answer.await_args_list[0]
            self.assertIn("количество 3", first_answer.args[0])

    async def test_ai_cart_quantity_rejects_exceeding_stock(self) -> None:
        async with self.maker() as session:
            tenant, user, product = await self._seed_runtime_product(session, quantity=5)
            orders_repo = OrdersRepo(session, tenant_id=tenant.id)
            await orders_repo.add_to_cart(user, product, "шт", 4)
            await session.commit()

            state = FakeState({"ai_cart_product_id": product.id, "ai_cart_size": "шт"})
            message = FakeMessage("2", user_id=user.tg_id)

            await ai_handlers.ai_cart_quantity_input(message, state, session)

            cart_items = await orders_repo.list_cart_items(user)
            self.assertEqual(len(cart_items), 1)
            self.assertEqual(cart_items[0].quantity, 4)
            message.answer.assert_awaited_once()
            self.assertIn("доступно только 1 шт", message.answer.await_args.args[0])

    async def test_cart_callback_can_increase_item_quantity(self) -> None:
        async with self.maker() as session:
            tenant, user, product = await self._seed_runtime_product(session, quantity=5)
            orders_repo = OrdersRepo(session, tenant_id=tenant.id)
            item = await orders_repo.add_to_cart(user, product, "шт", 2)
            await session.commit()

            callback_message = FakeMessage("", user_id=user.tg_id)
            callback = FakeCallback(f"cart:qty:{item.id}:1", callback_message, user_id=user.tg_id)

            await client_handlers.cq_cart_change_qty(callback, session)

            cart_items = await orders_repo.list_cart_items(user)
            self.assertEqual(len(cart_items), 1)
            self.assertEqual(cart_items[0].quantity, 3)
            callback.answer.assert_awaited_once()
            self.assertIn("Количество: 3 шт.", callback.answer.await_args.args[0])
            callback_message.answer.assert_awaited()

    async def test_cart_callback_does_not_reduce_below_one(self) -> None:
        async with self.maker() as session:
            tenant, user, product = await self._seed_runtime_product(session, quantity=5)
            orders_repo = OrdersRepo(session, tenant_id=tenant.id)
            item = await orders_repo.add_to_cart(user, product, "шт", 1)
            await session.commit()

            callback_message = FakeMessage("", user_id=user.tg_id)
            callback = FakeCallback(f"cart:qty:{item.id}:-1", callback_message, user_id=user.tg_id)

            await client_handlers.cq_cart_change_qty(callback, session)

            cart_items = await orders_repo.list_cart_items(user)
            self.assertEqual(len(cart_items), 1)
            self.assertEqual(cart_items[0].quantity, 1)
            callback.answer.assert_awaited_once()
            self.assertIn("Минимум для позиции: 1 шт.", callback.answer.await_args.args[0])

    async def test_cart_callback_respects_stock_limit(self) -> None:
        async with self.maker() as session:
            tenant, user, product = await self._seed_runtime_product(session, quantity=3)
            orders_repo = OrdersRepo(session, tenant_id=tenant.id)
            item = await orders_repo.add_to_cart(user, product, "шт", 3)
            await session.commit()

            callback_message = FakeMessage("", user_id=user.tg_id)
            callback = FakeCallback(f"cart:qty:{item.id}:1", callback_message, user_id=user.tg_id)

            await client_handlers.cq_cart_change_qty(callback, session)

            cart_items = await orders_repo.list_cart_items(user)
            self.assertEqual(len(cart_items), 1)
            self.assertEqual(cart_items[0].quantity, 3)
            callback.answer.assert_awaited_once()
            self.assertIn("доступно только 3 шт.", callback.answer.await_args.args[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)