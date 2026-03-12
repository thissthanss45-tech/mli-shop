from __future__ import annotations

import os
import tempfile
import unittest

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")
os.environ.setdefault("WEB_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("CORS_ORIGINS", "https://example.com")
os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///test_client_category_pagination_placeholder.db")

from database.catalog_repo import CatalogRepo  # noqa: E402
from database.db_manager import Base  # noqa: E402
from handlers import client as client_handlers  # noqa: E402
from models import Tenant  # noqa: E402


async def _create_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class ClientCategoryPaginationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmp_dir.name, "client_category_pagination.db")
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

    async def test_catalog_repo_lists_categories_paginated(self) -> None:
        async with self.maker() as session:
            tenant = Tenant(slug="flowers-boutique", title="Flowers Boutique", status="active")
            session.add(tenant)
            await session.flush()

            repo = CatalogRepo(session, tenant_id=tenant.id)
            for idx in range(1, 7):
                await repo.get_or_create_category(f"Категория {idx:02d}")
            await session.commit()

            total_count = await repo.count_categories()
            first_page = await repo.list_categories_paginated(page=1, page_size=5)
            second_page = await repo.list_categories_paginated(page=2, page_size=5)

            self.assertEqual(total_count, 6)
            self.assertEqual(len(first_page), 5)
            self.assertEqual(len(second_page), 1)

    def test_build_categories_keyboard_has_pagination_and_page_bound_category_callbacks(self) -> None:
        categories = [type("CategoryStub", (), {"id": idx, "name": f"Категория {idx}"})() for idx in range(1, 6)]

        kb = client_handlers.build_categories_kb(categories, page=1, total_count=6, page_size=5)
        markup = kb.as_markup()

        button_rows = markup.inline_keyboard
        self.assertEqual(button_rows[0][0].callback_data, "cat:1:1")
        self.assertEqual(button_rows[-1][0].text, "1/2")
        self.assertEqual(button_rows[-1][0].callback_data, "catalog:noop")
        self.assertEqual(button_rows[-1][1].callback_data, "catpage:2")

    def test_build_categories_keyboard_second_page_has_back_arrow(self) -> None:
        categories = [type("CategoryStub", (), {"id": 6, "name": "Категория 6"})()]

        kb = client_handlers.build_categories_kb(categories, page=2, total_count=6, page_size=5)
        markup = kb.as_markup()

        button_rows = markup.inline_keyboard
        self.assertEqual(button_rows[0][0].callback_data, "cat:2:6")
        self.assertEqual(button_rows[-1][0].callback_data, "catpage:1")
        self.assertEqual(button_rows[-1][1].callback_data, "catalog:noop")


if __name__ == "__main__":
    unittest.main(verbosity=2)