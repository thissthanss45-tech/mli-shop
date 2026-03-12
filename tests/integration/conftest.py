"""
Shared fixtures for integration tests.

Strategy:
- Each test gets a fresh file-based SQLite DB via pytest's tmp_path fixture.
- The async engine uses NullPool so connections are never shared across event
  loops — this avoids conflicts between asyncio.run() setup calls and
  TestClient's internal ASGI event loop.
- web_api.async_session_maker is patched to point at the test DB, then
  restored after the TestClient context exits.
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# ── Must be set BEFORE any project import ──────────────────────────────────
os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")
os.environ.setdefault("WEB_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("CORS_ORIGINS", "https://example.com")
os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///test_integration_placeholder.db")

# Disable effective rate-limiting for all tests in this process.
# RateLimitMiddleware reads RATE_LIMIT_MAX_REQUESTS at web_api import time, so
# this must be set before the first `import web_api`.
# 999_999 means we'll never hit the limit in any test run.
os.environ["RATE_LIMIT_MAX_REQUESTS"] = "999999"
# Point Redis at an invalid port so the rate-limiter always falls back
# gracefully (RuntimeError caught → call_next) even if the limit were hit.
os.environ.setdefault("REDIS_URL", "redis://localhost:0/0")

import web_api as _web_api  # noqa: E402
from database.db_manager import Base  # noqa: E402
from models import Brand, Category, Product, ProductStock  # noqa: E402
from utils.tenants import ensure_default_tenant  # noqa: E402

# ── Constants ──────────────────────────────────────────────────────────────
ADMIN_KEY = "test-admin-key"
ADMIN_HEADERS = {"Authorization": f"Bearer {ADMIN_KEY}"}
BAD_HEADERS = {"Authorization": "Bearer wrong-key"}


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_engine(db_path: str):
    """Create an async SQLite engine with NullPool (no inter-loop sharing)."""
    return create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )


async def _init_db(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _dispose_engine(engine) -> None:
    await engine.dispose()


async def _seed_product(
    maker: async_sessionmaker,
    *,
    title: str = "Air Max",
    category_name: str = "Footwear",
    brand_name: str = "Nike",
    sale_price: float = 2500.0,
    purchase_price: float = 1000.0,
    size: str = "M",
    quantity: int = 10,
    sku: str | None = None,
) -> dict:
    """Seed one product with stock; return a dict of IDs."""
    async with maker() as session:
        tenant = await ensure_default_tenant(session)
        cat = Category(name=category_name, tenant_id=tenant.id)
        brand = Brand(name=brand_name, tenant_id=tenant.id)
        session.add_all([cat, brand])
        await session.flush()

        product_sku = sku or f"{brand_name[:3].upper()}-000001"
        product = Product(
            tenant_id=tenant.id,
            title=title,
            description="Integration test product",
            purchase_price=Decimal(str(purchase_price)),
            sale_price=Decimal(str(sale_price)),
            category_id=cat.id,
            brand_id=brand.id,
            sku=product_sku,
        )
        session.add(product)
        await session.flush()

        stock = ProductStock(tenant_id=tenant.id, product_id=product.id, size=size, quantity=quantity)
        session.add(stock)
        await session.commit()

        return {
            "product_id": product.id,
            "category_id": cat.id,
            "brand_id": brand.id,
            "category_name": category_name,
            "brand_name": brand_name,
            "sale_price": sale_price,
            "size": size,
            "quantity": quantity,
        }


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture()
def db_client(tmp_path):
    """
    Yield a TestClient backed by a fresh empty SQLite DB.
    Use this fixture for tests that seed their own data or test empty-state paths.
    """
    engine = _make_engine(str(tmp_path / "test.db"))
    asyncio.run(_init_db(engine))
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    original_maker = _web_api.async_session_maker
    _web_api.async_session_maker = maker
    try:
        with TestClient(_web_api.app) as client:
            yield client
    finally:
        _web_api.async_session_maker = original_maker
        asyncio.run(_dispose_engine(engine))


@pytest.fixture()
def seeded_client(tmp_path):
    """
    Yield (TestClient, seed_meta) with one product already in the DB.
    seed_meta is the dict returned by _seed_product.
    """
    engine = _make_engine(str(tmp_path / "test.db"))
    asyncio.run(_init_db(engine))
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    seed_meta = asyncio.run(_seed_product(maker))

    original_maker = _web_api.async_session_maker
    _web_api.async_session_maker = maker
    try:
        with TestClient(_web_api.app) as client:
            yield client, seed_meta
    finally:
        _web_api.async_session_maker = original_maker
        asyncio.run(_dispose_engine(engine))
