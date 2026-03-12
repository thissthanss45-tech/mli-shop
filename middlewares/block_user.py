from __future__ import annotations

from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import settings
from models import User, UserRole
from models.users import normalize_role
from utils.tenants import is_runtime_owner, is_runtime_user_blocked


class BlockUserMiddleware(BaseMiddleware):
    def __init__(self, session_pool: async_sessionmaker[AsyncSession] | None = None) -> None:
        super().__init__()
        self.session_pool = session_pool

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        session: AsyncSession | None = data.get("session")
        if session is None and self.session_pool is None:
            return await handler(event, data)

        if isinstance(event, (Message, CallbackQuery)):
            from_user = event.from_user
        else:
            from_user = None

        if not from_user:
            return await handler(event, data)

        if self.session_pool is not None:
            async with self.session_pool() as session_ctx:
                if from_user.id == settings.owner_id or await is_runtime_owner(session_ctx, from_user.id):
                    return await handler(event, data)
                if await is_runtime_user_blocked(session_ctx, from_user.id):
                    if isinstance(event, CallbackQuery):
                        await event.answer("⛔ Вы заблокированы.", show_alert=True)
                    else:
                        await event.answer("⛔ Вы заблокированы.")
                    return None

        user = None
        if session is not None:
            stmt = select(User).where(User.tg_id == from_user.id)
            res = await session.execute(stmt)
            user = res.scalar_one_or_none()

            if from_user.id == settings.owner_id or await is_runtime_owner(session, from_user.id):
                return await handler(event, data)

        if session is not None and await is_runtime_user_blocked(session, from_user.id):
            if isinstance(event, CallbackQuery):
                await event.answer("⛔ Вы заблокированы.", show_alert=True)
            else:
                await event.answer("⛔ Вы заблокированы.")
            return None

        if user and normalize_role(user.role) != UserRole.CLIENT.value:
            return await handler(event, data)

        return await handler(event, data)


async def _is_blocked_user(user_id: int, session: AsyncSession) -> bool:
    stmt = select(User).where(User.tg_id == user_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    return bool(user and user.is_blocked)
