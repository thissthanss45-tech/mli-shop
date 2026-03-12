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
os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///test_web_product_media_placeholder.db")

from database.catalog_repo import CatalogRepo  # noqa: E402
from database.db_manager import Base  # noqa: E402
from utils.tenants import ensure_default_tenant  # noqa: E402
from web_api import _map_product  # noqa: E402


async def _create_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class WebProductMediaApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmp_dir.name, "web_product_media.db")
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

    async def test_map_product_exposes_primary_media_and_media_list(self) -> None:
        async with self.maker() as session:
            tenant = await ensure_default_tenant(session)
            repo = CatalogRepo(session, tenant_id=tenant.id)
            category = await repo.get_or_create_category("Монобукеты")
            brand = await repo.get_or_create_brand("Florist")
            product = await repo.create_product(
                title="Букет",
                purchase_price=1000,
                sale_price=1500,
                category=category,
                brand=brand,
            )
            await repo.add_photo(product, "video-file", media_type="video")
            await repo.add_photo(product, "photo-file", media_type="photo")
            await session.commit()

            loaded = await repo.get_product_with_details(product.id)
            payload = _map_product(loaded)

            self.assertEqual(payload.primary_media_type, "video")
            self.assertEqual(len(payload.media), 2)
            self.assertTrue(payload.primary_media_url.endswith(f"/api/products/{product.id}/media/{loaded.photos[0].id}"))
            self.assertTrue(payload.image_url.endswith("/image"))


if __name__ == "__main__":
    unittest.main(verbosity=2)