"""Вспомогательные функции для владельца."""

from functools import wraps
from typing import Any, Awaitable, Callable

from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from utils.tenants import is_runtime_owner


async def show_owner_main_menu(message: Message) -> None:
    """Главное меню владельца."""
    from .owner_keyboards import owner_main_menu_kb
    
    kb = owner_main_menu_kb()
    await message.answer("Главное меню владельца:", reply_markup=kb)


async def ensure_owner(event: Message | CallbackQuery, session: AsyncSession | None = None) -> bool:
    """Проверка: пользователь — владелец?"""
    from_user = event.from_user
    if session is not None and from_user:
        if await is_runtime_owner(session, from_user.id):
            return True

    if isinstance(event, CallbackQuery):
        await event.answer("⛔ Доступно только владельцу магазина.", show_alert=True)
        return False

    await event.answer("⛔ Доступно только владельцу магазина.")
    return False


def owner_only(handler: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Декоратор для ограничения хендлеров только владельцем."""

    @wraps(handler)
    async def wrapper(event: Message | CallbackQuery, *args: Any, **kwargs: Any) -> Any:
        session = kwargs.get("session")
        if session is None:
            for arg in args:
                if isinstance(arg, AsyncSession):
                    session = arg
                    break

        if not await ensure_owner(event, session):
            return None

        return await handler(event, *args, **kwargs)

    return wrapper