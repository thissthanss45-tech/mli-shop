"""Вспомогательные функции для владельца."""

from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import User, UserRole
from models.users import normalize_role


async def show_owner_main_menu(message: Message) -> None:
    """Главное меню владельца."""
    from .owner_keyboards import owner_main_menu_kb
    
    kb = owner_main_menu_kb()
    await message.answer("Главное меню владельца:", reply_markup=kb)


async def ensure_owner(message: Message, session: AsyncSession | None = None) -> bool:
    """Проверка: пользователь — владелец?"""
    owner_id = settings.owner_id
    if message.from_user and message.from_user.id == owner_id:
        return True

    if session is not None and message.from_user:
        stmt = select(User).where(User.tg_id == message.from_user.id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        if user and normalize_role(user.role) == UserRole.OWNER.value:
            return True

    await message.answer("⛔ Доступно только владельцу магазина.")
    return False