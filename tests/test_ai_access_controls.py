from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")
os.environ.setdefault("WEB_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("CORS_ORIGINS", "https://example.com")
os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///test_ai_access_placeholder.db")

import worker  # noqa: E402
from database.db_manager import Base  # noqa: E402
from handlers import ai as ai_handlers  # noqa: E402
from models import Category, Brand, Product, Tenant, User, UserRole  # noqa: E402
from utils.tenants import ensure_default_tenant, ensure_tenant_membership  # noqa: E402


class FakeState:
    def __init__(self) -> None:
        self._data: dict = {}

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)


class FakeMessage:
    def __init__(self, text: str, user_id: int) -> None:
        self.text = text
        self.chat = SimpleNamespace(id=user_id)
        self.from_user = SimpleNamespace(id=user_id, username=None, first_name="Test", last_name=None)
        self.answer = AsyncMock()


class FakeCallback:
    def __init__(self, data: str, user_id: int) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id, username=None, first_name="Test", last_name=None)
        self.message = SimpleNamespace(answer=AsyncMock())
        self.answer = AsyncMock()


class FakeStorage:
    def __init__(self) -> None:
        self.data: dict[tuple[int, int, int], dict] = {}

    async def get_data(self, key):
        return dict(self.data.get((key.bot_id, key.chat_id, key.user_id), {}))

    async def set_data(self, key, value):
        self.data[(key.bot_id, key.chat_id, key.user_id)] = dict(value)


class FakeBot:
    def __init__(self, token: str) -> None:
        self.token = token
        self.sent_messages: list[dict] = []

    async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None, reply_markup=None):
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
        )


class FakeIncomingMessage:
    def __init__(self, payload: dict) -> None:
        self.body = json.dumps(payload).encode("utf-8")
        self.headers = {}
        self.ack = AsyncMock()
        self.nack = AsyncMock()


async def _create_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class AIAccessControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmp_dir.name, "ai_access.db")
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

    async def test_runtime_owner_gets_ai_provider_chooser_without_admin_ids(self) -> None:
        async with self.maker() as session:
            tenant = await ensure_default_tenant(session)
            owner = User(tg_id=5001, tenant_id=tenant.id, role=UserRole.OWNER.value, ai_quota=0)
            session.add(owner)
            await session.flush()
            membership = await ensure_tenant_membership(session, owner, tenant.id, UserRole.OWNER.value)
            membership.role = UserRole.OWNER.value
            await session.commit()

            message = FakeMessage("✨ AI-Консультант", 5001)
            state = FakeState()
            fake_kb = SimpleNamespace(as_markup=lambda: "provider-markup")

            with patch.object(ai_handlers, "_get_available_ai_providers", return_value=["groq"]), \
                 patch.object(ai_handlers, "_build_provider_kb", return_value=fake_kb), \
                 patch.object(ai_handlers, "_start_ai_session", new=AsyncMock()) as start_mock:
                await ai_handlers.start_ai_chat(message, state, session)

            message.answer.assert_awaited_once()
            call = message.answer.await_args
            self.assertEqual(call.args[0], "Выберите AI провайдера:")
            self.assertEqual(call.kwargs.get("reply_markup"), "provider-markup")
            start_mock.assert_not_called()

    async def test_worker_uses_tenant_aware_broadcast_flag(self) -> None:
        engine = self.engine
        maker = self.maker
        original_maker = worker.async_session_maker
        worker.async_session_maker = maker

        try:
            async with maker() as session:
                tenant = await ensure_default_tenant(session)
                tenant.bot_token = worker.settings.bot_token
                await session.commit()

            fake_storage = FakeStorage()
            fake_bot = FakeBot(token=worker.settings.bot_token)
            incoming = FakeIncomingMessage(
                {
                    "chat_id": 5002,
                    "user_id": 5002,
                    "request_id": "ai-access-test",
                    "can_broadcast_ai_posts": True,
                    "messages": [
                        {"role": "system", "content": "system"},
                        {"role": "user", "content": "напиши пост для клиентов"},
                    ],
                }
            )

            with patch.object(worker, "_resolve_ai_config", AsyncMock(return_value=("groq", "key", "url", "model"))), \
                 patch.object(worker, "_request_ai", AsyncMock(return_value="Готовый пост")), \
                 patch.object(worker, "_persist_ai_chat_log", AsyncMock()), \
                 patch.object(worker, "_append_history", AsyncMock()), \
                 patch.object(worker, "_set_pending_post", AsyncMock()) as pending_post_mock, \
                 patch.object(worker, "_send_product_cards", AsyncMock()), \
                 patch.object(worker, "admin_kb", return_value="admin-markup"):
                await worker._process_message(fake_bot, fake_storage, incoming, bot_id=1)

            self.assertEqual(incoming.ack.await_count, 1)
            self.assertTrue(fake_bot.sent_messages)
            self.assertEqual(fake_bot.sent_messages[0]["reply_markup"], "admin-markup")
            pending_post_mock.assert_awaited_once()
        finally:
            worker.async_session_maker = original_maker

    async def test_worker_shows_broadcast_button_for_marketing_request_without_word_post(self) -> None:
        engine = self.engine
        maker = self.maker
        original_maker = worker.async_session_maker
        worker.async_session_maker = maker

        try:
            async with maker() as session:
                tenant = await ensure_default_tenant(session)
                tenant.bot_token = worker.settings.bot_token
                await session.commit()

            fake_storage = FakeStorage()
            fake_bot = FakeBot(token=worker.settings.bot_token)
            incoming = FakeIncomingMessage(
                {
                    "chat_id": 5003,
                    "user_id": 5003,
                    "request_id": "ai-broadcast-keyword-test",
                    "can_broadcast_ai_posts": True,
                    "messages": [
                        {"role": "system", "content": "system"},
                        {"role": "user", "content": "поздравь клиентов с 8 марта и сделай красивую рассылку"},
                    ],
                }
            )

            with patch.object(worker, "_resolve_ai_config", AsyncMock(return_value=("groq", "key", "url", "model"))), \
                 patch.object(worker, "_request_ai", AsyncMock(return_value="Дорогие клиенты! Поздравляем вас с праздником и дарим весеннее настроение.")), \
                 patch.object(worker, "_persist_ai_chat_log", AsyncMock()), \
                 patch.object(worker, "_append_history", AsyncMock()), \
                 patch.object(worker, "_set_pending_post", AsyncMock()) as pending_post_mock, \
                 patch.object(worker, "_send_product_cards", AsyncMock()), \
                 patch.object(worker, "admin_kb", return_value="admin-markup"):
                await worker._process_message(fake_bot, fake_storage, incoming, bot_id=1)

            self.assertEqual(incoming.ack.await_count, 1)
            self.assertTrue(fake_bot.sent_messages)
            self.assertEqual(fake_bot.sent_messages[0]["reply_markup"], "admin-markup")
            pending_post_mock.assert_awaited_once()
        finally:
            worker.async_session_maker = original_maker

    async def test_staff_ai_request_sets_broadcast_flag_for_queue(self) -> None:
        async with self.maker() as session:
            tenant = await ensure_default_tenant(session)
            staff_user = User(tg_id=5004, tenant_id=tenant.id, role=UserRole.STAFF.value, ai_quota=5)
            session.add(staff_user)
            await session.flush()
            membership = await ensure_tenant_membership(session, staff_user, tenant.id, UserRole.STAFF.value)
            membership.role = UserRole.STAFF.value
            await session.commit()

            message = FakeMessage("напиши пост про весеннюю акцию", 5004)
            state = FakeState()

            with patch.object(ai_handlers, "send_task_to_queue", new=AsyncMock(return_value="req-1")) as queue_mock, \
                 patch.object(ai_handlers, "get_user_cart_context", new=AsyncMock(return_value="")):
                await ai_handlers._process_ai_input_text(message, state, session, message.text)

            queue_mock.assert_awaited_once()
            payload = queue_mock.await_args.args[1]
            self.assertTrue(payload["can_broadcast_ai_posts"])

    async def test_client_context_uses_runtime_tenant_and_tenant_cache_key(self) -> None:
        async with self.maker() as session:
            runtime_tenant = Tenant(
                slug="flowers-boutique",
                title="Flowers Boutique",
                status="active",
                bot_token=os.environ["BOT_TOKEN"],
            )
            session.add(runtime_tenant)
            await session.flush()

            default_tenant = await ensure_default_tenant(session)

            runtime_repo = ai_handlers.CatalogRepo(session, tenant_id=runtime_tenant.id)
            runtime_category = await runtime_repo.get_or_create_category("Монобукеты")
            runtime_brand = await runtime_repo.get_or_create_brand("Florist")
            await runtime_repo.create_product(
                title="Пион",
                purchase_price=1000,
                sale_price=1500,
                category=runtime_category,
                brand=runtime_brand,
            )
            runtime_product = await runtime_repo.get_all_products_with_stock()
            await runtime_repo.add_stock(runtime_product[0], "standard", 3)

            default_repo = ai_handlers.CatalogRepo(session, tenant_id=default_tenant.id)
            default_category = await default_repo.get_or_create_category("Чужая")
            default_brand = await default_repo.get_or_create_brand("Other")
            await default_repo.create_product(
                title="Чужой товар",
                purchase_price=500,
                sale_price=900,
                category=default_category,
                brand=default_brand,
            )
            await session.commit()

            with patch.object(ai_handlers, "_get_cached_context", new=AsyncMock(return_value=None)) as get_cache_mock, \
                 patch.object(ai_handlers, "_set_cached_context", new=AsyncMock()) as set_cache_mock:
                context = await ai_handlers.get_client_context(session)

            self.assertIn("Пион", context)
            self.assertNotIn("Чужой товар", context)
            get_cache_mock.assert_awaited_once_with(f"{ai_handlers.CLIENT_CONTEXT_CACHE_KEY}:{runtime_tenant.id}")
            set_cache_mock.assert_awaited_once()
            self.assertEqual(set_cache_mock.await_args.args[0], f"{ai_handlers.CLIENT_CONTEXT_CACHE_KEY}:{runtime_tenant.id}")

    async def test_ai_cart_add_rejects_product_from_other_tenant(self) -> None:
        async with self.maker() as session:
            runtime_tenant = Tenant(
                slug="flowers-boutique",
                title="Flowers Boutique",
                status="active",
                bot_token=os.environ["BOT_TOKEN"],
            )
            other_tenant = Tenant(
                slug="other-shop",
                title="Other Shop",
                status="active",
                bot_token="other-token",
            )
            session.add_all([runtime_tenant, other_tenant])
            await session.flush()

            owner = User(tg_id=5003, tenant_id=runtime_tenant.id, role=UserRole.CLIENT.value, ai_quota=0)
            session.add(owner)
            await session.flush()
            membership = await ensure_tenant_membership(session, owner, runtime_tenant.id, UserRole.CLIENT.value)
            membership.role = UserRole.CLIENT.value

            category = Category(name="Чужая категория", tenant_id=other_tenant.id)
            brand = Brand(name="Чужой бренд", tenant_id=other_tenant.id)
            session.add_all([category, brand])
            await session.flush()

            foreign_product = Product(
                tenant_id=other_tenant.id,
                sku="FOR-000001",
                title="Чужой товар",
                purchase_price=100,
                sale_price=200,
                category_id=category.id,
                brand_id=brand.id,
            )
            session.add(foreign_product)
            await session.commit()

            callback = FakeCallback(f"ai_cart_add:{foreign_product.id}", user_id=5003)
            state = FakeState()
            await ai_handlers.ai_cart_add(callback, state, session)

            callback.answer.assert_awaited_once_with("Товар не найден", show_alert=True)
            self.assertEqual(await state.get_data(), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)