from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import settings


class Base(AsyncAttrs, DeclarativeBase):
    """Базовый класс для всех моделей."""
    pass


# Создаем движок
engine = create_async_engine(
    settings.db_url,
    echo=False,  # Можно включить True для отладки SQL запросов
    future=True,
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

