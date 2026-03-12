from __future__ import annotations

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
os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///test_owner_product_creation_placeholder.db")

from database.catalog_repo import CatalogRepo  # noqa: E402
from database.db_manager import Base  # noqa: E402
from handlers import owner_products  # noqa: E402
from models import Tenant, User, UserRole  # noqa: E402
from utils.tenants import ensure_default_tenant, ensure_tenant_membership  # noqa: E402


async def _create_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class FakeState:
    def __init__(self, data: dict | None = None) -> None:
        self._data = dict(data or {})
        self.clear = AsyncMock()
        self.set_state = AsyncMock()

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)


class FakeBot:
    def __init__(self) -> None:
        self.send_message = AsyncMock()
        self.send_photo = AsyncMock()
        self.send_video = AsyncMock()


class FakeMessage:
    def __init__(self, text: str = "", user_id: int = 1) -> None:
        self.text = text
        self.chat = SimpleNamespace(id=user_id)
        self.from_user = SimpleNamespace(id=user_id, username=None, first_name="Owner", last_name=None)
        self.answer = AsyncMock()
        self.bot = FakeBot()
        self.photo = None
        self.video = None


class OwnerProductCreationSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmp_dir.name, "owner_product_creation.db")
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

    async def _seed_runtime_tenant(self, session: AsyncSession) -> Tenant:
        tenant = Tenant(
            slug="flowers-boutique",
            title="Flowers Boutique",
            status="active",
            bot_token=os.environ["BOT_TOKEN"],
        )
        session.add(tenant)
        await session.flush()

        owner = User(tg_id=1, tenant_id=tenant.id, role=UserRole.OWNER.value, ai_quota=0)
        session.add(owner)
        await session.flush()
        membership = await ensure_tenant_membership(session, owner, tenant.id, UserRole.OWNER.value)
        membership.role = UserRole.OWNER.value

        await ensure_default_tenant(session)
        await session.commit()
        return tenant

    async def _seed_catalog(self, session: AsyncSession) -> tuple[Tenant, int, int]:
        tenant = await self._seed_runtime_tenant(session)
        repo = CatalogRepo(session, tenant_id=tenant.id)
        category = await repo.get_or_create_category("Монобукеты")
        brand = await repo.get_or_create_brand("Florist")
        await session.commit()
        return tenant, category.id, brand.id

    async def _create_product_with_media(self, media_payload: list[dict[str, str]]) -> list[tuple[str, str]]:
        async with self.maker() as session:
            tenant, category_id, brand_id = await self._seed_catalog(session)
            state = FakeState(
                {
                    "category_id": category_id,
                    "brand_id": brand_id,
                    "name": "Букет дня",
                    "purchase_price": 1000,
                    "sale_price": 1900,
                    "sizes": ["ONE"],
                    "quantities": {"ONE": 5},
                    "media": media_payload,
                }
            )
            message = FakeMessage()

            with patch.object(owner_products, "show_owner_main_menu", new=AsyncMock()):
                await owner_products.create_product_in_db(message, state, session)

            repo = CatalogRepo(session, tenant_id=tenant.id)
            products = await repo.get_all_products_with_stock()
            self.assertEqual(len(products), 1)
            loaded = await repo.get_product_with_details(products[0].id)
            self.assertIsNotNone(loaded)
            return [(item.file_id, item.media_type) for item in loaded.photos]

    async def test_owner_add_category_uses_runtime_tenant(self) -> None:
        async with self.maker() as session:
            tenant = await self._seed_runtime_tenant(session)
            state = FakeState()
            message = FakeMessage("Розы")

            with patch.object(owner_products, "owner_menu_products", new=AsyncMock()):
                await owner_products.owner_add_category_name(message, state, session)

            repo = CatalogRepo(session, tenant_id=tenant.id)
            categories = await repo.list_categories()
            self.assertEqual([item.name for item in categories], ["Розы"])

    async def test_owner_add_product_shows_only_runtime_categories(self) -> None:
        async with self.maker() as session:
            tenant = await self._seed_runtime_tenant(session)
            runtime_repo = CatalogRepo(session, tenant_id=tenant.id)
            await runtime_repo.get_or_create_category("Розы")
            await session.flush()

            session.add(Tenant(slug="other-shop", title="Other", status="active", bot_token="other-token"))
            await session.flush()
            session.add(owner_products.Category(name="Чужая категория", tenant_id=None))
            await session.commit()

            message = FakeMessage(user_id=1)
            state = FakeState()

            with patch.object(owner_products, "build_categories_kb", side_effect=lambda categories: [item.name for item in categories]) as kb_mock:
                await owner_products.owner_add_product_start.__wrapped__(message, state, session)

            categories_arg = kb_mock.call_args.args[0]
            self.assertEqual([item.name for item in categories_arg], ["Розы"])
            message.answer.assert_awaited_once()

    async def test_create_product_with_photo_media(self) -> None:
        items = await self._create_product_with_media([
            {"file_id": "photo-1", "media_type": "photo"},
        ])
        self.assertEqual(items, [("photo-1", "photo")])

    async def test_create_product_with_video_media(self) -> None:
        items = await self._create_product_with_media([
            {"file_id": "video-1", "media_type": "video"},
        ])
        self.assertEqual(items, [("video-1", "video")])

    async def test_create_product_with_mixed_media(self) -> None:
        items = await self._create_product_with_media(
            [
                {"file_id": "video-1", "media_type": "video"},
                {"file_id": "photo-1", "media_type": "photo"},
            ]
        )
        self.assertEqual(items, [("video-1", "video"), ("photo-1", "photo")])

    async def test_cancel_routes_back_on_each_text_step(self) -> None:
        session = object()
        cases = [
            (owner_products.owner_enter_name, FakeState()),
            (owner_products.owner_enter_purchase_price, FakeState()),
            (owner_products.owner_enter_sale_price, FakeState()),
            (owner_products.owner_enter_sizes, FakeState()),
            (
                owner_products.owner_enter_quantity_for_size,
                FakeState({"sizes": ["ONE"], "current_size_index": 0, "quantities": {}}),
            ),
        ]

        for handler, state in cases:
            message = FakeMessage("Отмена")
            with patch.object(owner_products, "owner_menu_products", new=AsyncMock()) as menu_mock:
                await handler(message, state, session)
            state.clear.assert_awaited()
            menu_mock.assert_awaited_once_with(message, state, session)


if __name__ == "__main__":
    unittest.main(verbosity=2)