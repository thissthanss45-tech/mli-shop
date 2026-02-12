from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.engine import make_url

from config import settings


class Base(AsyncAttrs, DeclarativeBase):
    """Базовый класс для всех моделей."""
    pass


# Создаем движок с конфигурируемым пулом (для PostgreSQL/MySQL).
_engine_kwargs: dict[str, object] = {
    "echo": False,
    "future": True,
    "pool_pre_ping": True,
}

_db_backend = make_url(settings.db_url).get_backend_name()
if _db_backend != "sqlite":  # SQLite использует NullPool, поэтому настраиваем только внешние БД
    _engine_kwargs.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
    )

engine = create_async_engine(
    settings.db_url,
    **_engine_kwargs,
)

# Фабрика сессий (используется в Middleware)
async_session_maker = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def init_db() -> None:
    """Создание таблиц (для простого старта без Alembic)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

