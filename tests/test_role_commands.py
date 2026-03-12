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
os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///test_role_commands_placeholder.db")

from database.db_manager import Base  # noqa: E402
from handlers.admin import set_staff_role  # noqa: E402
from handlers.owner_main_parts.promo_menu_support import owner_add_owner, owner_remove_owner  # noqa: E402
from models import Tenant, User, UserRole  # noqa: E402
from models.users import normalize_role  # noqa: E402
from shop import unset_staff_handler  # noqa: E402
from utils.tenants import ensure_default_tenant, ensure_tenant_membership, get_membership_for_user  # noqa: E402


class FakeMessage:
    def __init__(self, text: str, from_user_id: int) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=from_user_id, username=None, first_name=None, last_name=None)
        self.answer = AsyncMock()
        self.bot = SimpleNamespace(send_message=AsyncMock())


async def _create_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class RoleCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmp_dir.name, "role_commands.db")
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

    async def _create_user_with_membership(
        self,
        session: AsyncSession,
        *,
        tg_id: int,
        tenant_id: int,
        role: str,
    ) -> User:
        user = User(tg_id=tg_id, tenant_id=tenant_id, role=role, ai_quota=0)
        session.add(user)
        await session.flush()
        membership = await ensure_tenant_membership(session, user, tenant_id, role)
        membership.role = role
        await session.flush()
        return user

    async def _create_secondary_tenant(self, session: AsyncSession, slug: str) -> Tenant:
        tenant = Tenant(slug=slug, title=slug.title(), status="active")
        session.add(tenant)
        await session.flush()
        return tenant

    async def test_add_owner_upgrades_existing_tenant_membership(self) -> None:
        async with self.maker() as session:
            tenant = await self._seed_runtime_owner(session)
            user = await self._create_user_with_membership(
                session,
                tg_id=2002,
                tenant_id=tenant.id,
                role=UserRole.CLIENT.value,
            )
            await session.commit()

            message = FakeMessage("/add_owner 2002", from_user_id=1)
            await owner_add_owner(message, session)

            membership = await get_membership_for_user(session, user, tenant.id)
            self.assertIsNotNone(membership)
            self.assertEqual(normalize_role(membership.role), UserRole.OWNER.value)
            self.assertEqual(normalize_role(user.role), UserRole.OWNER.value)

    async def test_remove_owner_demotes_current_tenant_but_keeps_global_owner_if_other_tenant_exists(self) -> None:
        async with self.maker() as session:
            tenant = await self._seed_runtime_owner(session)
            user = await self._create_user_with_membership(
                session,
                tg_id=2003,
                tenant_id=tenant.id,
                role=UserRole.OWNER.value,
            )
            other_tenant = await self._create_secondary_tenant(session, "other-owner-store")
            other_membership = await ensure_tenant_membership(session, user, other_tenant.id, UserRole.OWNER.value)
            other_membership.role = UserRole.OWNER.value
            await session.commit()

            message = FakeMessage("/remove_owner 2003", from_user_id=1)
            await owner_remove_owner(message, session)

            current_membership = await get_membership_for_user(session, user, tenant.id)
            fallback_membership = await get_membership_for_user(session, user, other_tenant.id)
            self.assertIsNotNone(current_membership)
            self.assertEqual(normalize_role(current_membership.role), UserRole.CLIENT.value)
            self.assertIsNotNone(fallback_membership)
            self.assertEqual(normalize_role(fallback_membership.role), UserRole.OWNER.value)
            self.assertEqual(normalize_role(user.role), UserRole.OWNER.value)

    async def test_set_seller_updates_current_tenant_membership_and_preserves_other_owner_role(self) -> None:
        async with self.maker() as session:
            tenant = await self._seed_runtime_owner(session)
            user = await self._create_user_with_membership(
                session,
                tg_id=2004,
                tenant_id=tenant.id,
                role=UserRole.CLIENT.value,
            )
            other_tenant = await self._create_secondary_tenant(session, "other-seller-store")
            other_membership = await ensure_tenant_membership(session, user, other_tenant.id, UserRole.OWNER.value)
            other_membership.role = UserRole.OWNER.value
            await session.commit()

            message = FakeMessage("/set_seller 2004", from_user_id=1)
            await set_staff_role(message, session)

            current_membership = await get_membership_for_user(session, user, tenant.id)
            self.assertIsNotNone(current_membership)
            self.assertEqual(normalize_role(current_membership.role), UserRole.STAFF.value)
            self.assertEqual(normalize_role(user.role), UserRole.OWNER.value)

    async def test_unstaff_demotes_current_tenant_but_preserves_other_owner_role(self) -> None:
        async with self.maker() as session:
            tenant = await self._seed_runtime_owner(session)
            user = await self._create_user_with_membership(
                session,
                tg_id=2005,
                tenant_id=tenant.id,
                role=UserRole.STAFF.value,
            )
            other_tenant = await self._create_secondary_tenant(session, "other-unstaff-store")
            other_membership = await ensure_tenant_membership(session, user, other_tenant.id, UserRole.OWNER.value)
            other_membership.role = UserRole.OWNER.value
            await session.commit()

            message = FakeMessage("/unstaff 2005", from_user_id=1)
            await unset_staff_handler(message, session)

            current_membership = await get_membership_for_user(session, user, tenant.id)
            self.assertIsNotNone(current_membership)
            self.assertEqual(normalize_role(current_membership.role), UserRole.CLIENT.value)
            self.assertEqual(normalize_role(user.role), UserRole.OWNER.value)


if __name__ == "__main__":
    unittest.main(verbosity=2)