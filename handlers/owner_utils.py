"""Вспомогательные функции для владельца."""

from aiogram.types import Message, CallbackQuery
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


async def ensure_owner(event: Message | CallbackQuery, session: AsyncSession | None = None) -> bool:
    """Проверка: пользователь — владелец?"""
    owner_id = settings.owner_id
    from_user = event.from_user
    if from_user and from_user.id == owner_id:
        return True

    if session is not None and from_user:
        stmt = select(User).where(User.tg_id == from_user.id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        if user and normalize_role(user.role) == UserRole.OWNER.value:
            return True

    if isinstance(event, CallbackQuery):
        await event.answer("⛔ Доступно только владельцу магазина.", show_alert=True)
        return False

    await event.answer("⛔ Доступно только владельцу магазина.")
    return False