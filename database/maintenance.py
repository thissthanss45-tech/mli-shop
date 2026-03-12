from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

import models  # noqa: F401

from database.db_manager import Base, engine


async def reset_database_data(target_engine: AsyncEngine | None = None) -> int:
    active_engine = target_engine or engine
    backend = make_url(str(active_engine.url)).get_backend_name()
    table_names = [table.name for table in Base.metadata.sorted_tables]

    if not table_names:
        return 0

    async with active_engine.begin() as conn:
        if backend == "postgresql":
            preparer = conn.dialect.identifier_preparer
            quoted_tables = ", ".join(preparer.quote(name) for name in table_names)
            await conn.execute(text(f"TRUNCATE TABLE {quoted_tables} RESTART IDENTITY CASCADE"))
            return len(table_names)

        if backend == "sqlite":
            await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            for table_name in reversed(table_names):
                await conn.execute(text(f'DELETE FROM "{table_name}"'))
            try:
                await conn.execute(text("DELETE FROM sqlite_sequence"))
            except Exception:
                pass
            await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            return len(table_names)

        for table_name in reversed(table_names):
            await conn.execute(text(f'DELETE FROM "{table_name}"'))

    return len(table_names)