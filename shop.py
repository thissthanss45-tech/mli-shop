from __future__ import annotations

import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.fsm.storage.redis import RedisStorage 
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from config import settings
from database import init_db, async_session_maker
from models import User, UserRole
from models.users import normalize_role

from middlewares.db import DbSessionMiddleware
from middlewares.block_user import BlockUserMiddleware
from handlers import client_router, product_router, main_router, ai_router, admin_router, warehouse_router

# Настройка логгера
logger.remove()
logger.add(sys.stderr, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>")
logger.add("bot_logs.log", rotation="5 MB", compression="zip", level="INFO")


async def start_handler(message: Message, session: AsyncSession) -> None:
    stmt = select(User).where(User.tg_id == message.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    if user is None:
        role = (
            UserRole.OWNER.value
            if message.from_user.id == settings.owner_id
            else UserRole.CLIENT.value
        )
        user = User(
            tg_id=message.from_user.id,
            username=message.from_user.username,
            role=role,
            ai_quota=settings.ai_client_start_quota
        )
        session.add(user)
        await session.commit()
    elif user.is_blocked and message.from_user.id != settings.owner_id:
        await message.answer("⛔ Вы заблокированы.")
        return

    # Меню по ролям
    if normalize_role(user.role) == UserRole.OWNER.value:
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text="📦 Товары"),
                    KeyboardButton(text="📊 Склад"),
                ],
                [
                    KeyboardButton(text="📋 Заказы"),
                    KeyboardButton(text="📈 Статистика"),
                ],
                [
                    KeyboardButton(text="✨ AI-Консультант"),
                    KeyboardButton(text="🔙 Отмена"),
                ],
            ],
            resize_keyboard=True,
        )
        text = f"👑 Привет, владелец {message.from_user.first_name}!\nВыбери действие:"
    
    elif normalize_role(user.role) == UserRole.STAFF.value:
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🛍 Каталог"), KeyboardButton(text="📋 Заказы")],
                [KeyboardButton(text="💳 Касса")],
            ],
            resize_keyboard=True,
        )
        text = f"👔 Привет, сотрудник {message.from_user.first_name}!\nТвой рабочий терминал готов."
    else:
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🛍 Каталог"), KeyboardButton(text="🛒 Корзина")],
                [KeyboardButton(text="📦 Мои заказы"), KeyboardButton(text="✨ AI-Консультант")],
                [KeyboardButton(text="💬 Продавец"), KeyboardButton(text="💬 Владелец")],
            ],
            resize_keyboard=True,
        )
        text = f"Привет, {message.from_user.first_name}!\nВыбери действие:"

    await message.answer(text, reply_markup=kb)


async def set_staff_handler(message: Message, session: AsyncSession) -> None:
    if message.from_user.id != settings.owner_id:
        await message.answer("Эта команда доступна только владельцу.")
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Используй: /staff <telegram_id>")
        return
    target_tg_id = int(parts[1])
    stmt = select(User).where(User.tg_id == target_tg_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if user is None:
        await message.answer(f"Пользователь {target_tg_id} не найден.")
        return
    user.role = UserRole.STAFF.value
    await session.commit()
    await message.answer(f"✅ Пользователь {target_tg_id} теперь STAFF.")


async def unset_staff_handler(message: Message, session: AsyncSession) -> None:
    if message.from_user.id != settings.owner_id:
        await message.answer("Эта команда доступна только владельцу.")
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Используй: /unstaff <telegram_id>")
        return
    target_tg_id = int(parts[1])
    stmt = select(User).where(User.tg_id == target_tg_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if user is None:
        await message.answer(f"Пользователь {target_tg_id} не найден.")
        return
    user.role = UserRole.CLIENT.value
    await session.commit()
    await message.answer(f"✅ Пользователь {target_tg_id} теперь CLIENT.")


async def on_startup() -> None:
    logger.info("Инициализация БД…")
    await init_db()
    logger.info("БД готова.")


def setup_routers(dp: Dispatcher) -> None:
    dp.include_router(admin_router)
    dp.include_router(ai_router)
    dp.include_router(product_router)
    dp.include_router(warehouse_router)  # 👈 НОВЫЙ СКЛАД
    dp.include_router(main_router)
    dp.include_router(client_router)


async def main() -> None:
    bot = Bot(token=settings.bot_token)
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)

    db_session_mw = DbSessionMiddleware(session_pool=async_session_maker)
    block_user_mw = BlockUserMiddleware(session_pool=async_session_maker)

    dp.update.middleware(db_session_mw)
    dp.message.middleware(block_user_mw)
    dp.callback_query.middleware(block_user_mw)

    dp.message.register(start_handler, CommandStart())
    dp.message.register(set_staff_handler, Command("staff"))
    dp.message.register(unset_staff_handler, Command("unstaff"))

    setup_routers(dp)

    await on_startup()
    logger.info("Запускаю бота…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
