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
os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///test_tenant_blocking_placeholder.db")

from database.db_manager import Base  # noqa: E402
from handlers.owner_main_parts.promo_menu_support import owner_block_user, owner_unblock_user  # noqa: E402
from models import Tenant, User, UserRole  # noqa: E402
from utils.tenants import (  # noqa: E402
    ensure_default_tenant,
    ensure_tenant_membership,
    get_membership_for_user,
    is_runtime_user_blocked,
    is_user_blocked_in_tenant,
)


class FakeMessage:
    def __init__(self, text: str, from_user_id: int) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=from_user_id, username=None, first_name=None, last_name=None)
        self.answer = AsyncMock()
        self.bot = SimpleNamespace(send_message=AsyncMock())


async def _create_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class TenantBlockingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmp_dir.name, "tenant_blocking.db")
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

    async def _seed_runtime_owner(self, session: AsyncSession) -> Tenant:
        tenant = await ensure_default_tenant(session)
        owner = User(tg_id=1, tenant_id=tenant.id, username="owner", role=UserRole.OWNER.value, ai_quota=0)
        session.add(owner)
        await session.flush()
        membership = await ensure_tenant_membership(session, owner, tenant.id, UserRole.OWNER.value)
        membership.role = UserRole.OWNER.value
        await session.commit()
        return tenant

    async def _create_other_tenant(self, session: AsyncSession, slug: str) -> Tenant:
        tenant = Tenant(slug=slug, title=slug.title(), status="active")
        session.add(tenant)
        await session.flush()
        return tenant

    async def test_block_command_only_blocks_current_tenant_membership(self) -> None:
        async with self.maker() as session:
            runtime_tenant = await self._seed_runtime_owner(session)
            other_tenant = await self._create_other_tenant(session, "other-block-store")
            user = User(tg_id=3001, tenant_id=runtime_tenant.id, role=UserRole.CLIENT.value, ai_quota=0)
            session.add(user)
            await session.flush()

            runtime_membership = await ensure_tenant_membership(session, user, runtime_tenant.id, UserRole.CLIENT.value)
            runtime_membership.role = UserRole.CLIENT.value
            other_membership = await ensure_tenant_membership(session, user, other_tenant.id, UserRole.CLIENT.value)
            other_membership.role = UserRole.CLIENT.value
            await session.commit()

            await owner_block_user(FakeMessage("/block 3001", from_user_id=1), session)

            runtime_membership = await get_membership_for_user(session, user, runtime_tenant.id)
            other_membership = await get_membership_for_user(session, user, other_tenant.id)
            self.assertIsNotNone(runtime_membership)
            self.assertTrue(bool(runtime_membership and runtime_membership.is_blocked))
            self.assertIsNotNone(other_membership)
            self.assertFalse(bool(other_membership and other_membership.is_blocked))

            await owner_unblock_user(FakeMessage("/unblock 3001", from_user_id=1), session)
            runtime_membership = await get_membership_for_user(session, user, runtime_tenant.id)
            self.assertFalse(bool(runtime_membership and runtime_membership.is_blocked))

    async def test_runtime_block_check_ignores_other_tenant_block(self) -> None:
        async with self.maker() as session:
            runtime_tenant = await self._seed_runtime_owner(session)
            other_tenant = await self._create_other_tenant(session, "other-runtime-store")
            user = User(tg_id=3002, tenant_id=runtime_tenant.id, role=UserRole.CLIENT.value, ai_quota=0)
            session.add(user)
            await session.flush()

            runtime_membership = await ensure_tenant_membership(session, user, runtime_tenant.id, UserRole.CLIENT.value)
            runtime_membership.role = UserRole.CLIENT.value
            other_membership = await ensure_tenant_membership(session, user, other_tenant.id, UserRole.CLIENT.value)
            other_membership.role = UserRole.CLIENT.value
            other_membership.is_blocked = True
            await session.commit()

            self.assertFalse(await is_runtime_user_blocked(session, 3002))
            self.assertFalse(await is_user_blocked_in_tenant(session, 3002, runtime_tenant.id))
            self.assertTrue(await is_user_blocked_in_tenant(session, 3002, other_tenant.id))


if __name__ == "__main__":
    unittest.main(verbosity=2)