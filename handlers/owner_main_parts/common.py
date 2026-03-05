from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import User, UserRole
from models.users import normalize_role
from ..owner_utils import show_owner_main_menu

main_router = Router(name="owner_main")
logger = logging.getLogger(__name__)


async def _send_correct_menu(message: Message, session: AsyncSession):
    if message.from_user.id == settings.owner_id:
        await show_owner_main_menu(message)
        return

    stmt = select(User).where(User.tg_id == message.from_user.id)
    user = (await session.execute(stmt)).scalar_one_or_none()

    if user and normalize_role(user.role) == UserRole.STAFF.value:
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🛍 Каталог"), KeyboardButton(text="📋 Заказы")],
                [KeyboardButton(text="💳 Касса")],
            ],
            resize_keyboard=True,
        )
        await message.answer("✅ Меню сотрудника:", reply_markup=kb)
    else:
        await message.answer("✅ Отменено.", reply_markup=None)


async def _is_owner_or_staff(user_id: int, session: AsyncSession) -> bool:
    if user_id == settings.owner_id:
        return True
    stmt = select(User).where(User.tg_id == user_id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    return bool(user and normalize_role(user.role) == UserRole.STAFF.value)


async def _require_owner_or_staff(message: Message, session: AsyncSession) -> bool:
    if await _is_owner_or_staff(message.from_user.id, session):
        return True
    await message.answer("⛔ Только для персонала.")
    return False


async def _require_owner_or_staff_cb(callback: CallbackQuery, session: AsyncSession) -> bool:
    if await _is_owner_or_staff(callback.from_user.id, session):
        return True
    await callback.answer("⛔ Только для персонала.", show_alert=True)
    return False
