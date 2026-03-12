from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from models import UserRole
from utils.tenants import get_runtime_tenant_role_for_tg_id, is_runtime_owner_or_staff
from ..owner_utils import show_owner_main_menu

main_router = Router(name="owner_main")
logger = logging.getLogger(__name__)


async def _send_correct_menu(message: Message, session: AsyncSession):
    role = await get_runtime_tenant_role_for_tg_id(session, message.from_user.id)
    if role == UserRole.OWNER.value:
        await show_owner_main_menu(message)
        return

    if role == UserRole.STAFF.value:
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
    return await is_runtime_owner_or_staff(session, user_id)


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
