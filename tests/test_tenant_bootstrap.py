from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")
os.environ.setdefault("WEB_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("CORS_ORIGINS", "https://example.com")
os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///test_tenant_placeholder.db")

from database.db_manager import Base
from models import Tenant, TenantSettings
from utils.tenants import DEFAULT_TENANT_SLUG, ensure_default_tenant, get_or_create_tenant_settings


async def _create_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _dispose_engine(engine) -> None:
    await engine.dispose()


class TenantBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmp_dir.name, "tenant_test.db")
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            poolclass=NullPool,
        )
        self.maker = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        asyncio.run(_create_schema(self.engine))

    def tearDown(self) -> None:
        asyncio.run(_dispose_engine(self.engine))
        self._tmp_dir.cleanup()

    def test_default_tenant_and_settings_are_created_once(self) -> None:
        asyncio.run(self._assert_default_tenant())

    def test_default_tenant_does_not_duplicate_existing_bot_token(self) -> None:
        asyncio.run(self._assert_default_tenant_skips_duplicate_bot_token())

    async def _assert_default_tenant(self) -> None:
        async with self.maker() as session:
            tenant = await ensure_default_tenant(session)
            settings = await get_or_create_tenant_settings(session, tenant.id)
            await session.commit()

            self.assertEqual(tenant.slug, DEFAULT_TENANT_SLUG)
            self.assertTrue(settings.menu_client)
            self.assertTrue(settings.menu_staff)
            self.assertTrue(settings.menu_owner)

        async with self.maker() as session:
            tenant_res = await session.execute(select(Tenant))
            settings_res = await session.execute(select(TenantSettings))
            self.assertEqual(len(tenant_res.scalars().all()), 1)
            self.assertEqual(len(settings_res.scalars().all()), 1)

    async def _assert_default_tenant_skips_duplicate_bot_token(self) -> None:
        async with self.maker() as session:
            session.add(
                Tenant(
                    slug="flowers-boutique",
                    title="Flowers Boutique",
                    status="active",
                    bot_token=os.environ["BOT_TOKEN"],
                    admin_api_key="tenant-secret-key",
                )
            )
            await session.commit()

        async with self.maker() as session:
            tenant = await ensure_default_tenant(session)
            await session.commit()
            self.assertEqual(tenant.slug, DEFAULT_TENANT_SLUG)
            self.assertNotEqual(tenant.bot_token, os.environ["BOT_TOKEN"])


if __name__ == "__main__":
    unittest.main(verbosity=2)