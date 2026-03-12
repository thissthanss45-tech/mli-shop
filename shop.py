from __future__ import annotations

import asyncio
import secrets
import sys
import time

from aiogram import Bot, Dispatcher
from aiogram.types import ErrorEvent
from aiogram.exceptions import TelegramBadRequest
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
from middlewares.trace import TraceMiddleware
from utils.tenants import (
    ensure_tenant_membership,
    get_or_create_default_tenant_user,
    get_or_create_tenant_settings,
    get_primary_owner_tg_id,
    get_role_for_user,
    is_runtime_owner,
    is_user_blocked_in_tenant,
    resolve_tenant_by_bot_token,
    sync_user_role_from_memberships,
)
from utils.trace import get_trace_id
from handlers import (
    client_router,
    product_router,
    main_router,
    ai_router,
    admin_router,
    warehouse_router,
    admin_orders_router,
)

# Настройка логгера
logger.remove()


def _trace_patcher(record):
    record["extra"].setdefault("trace_id", get_trace_id())


logger.configure(patcher=_trace_patcher)
logger.add(
    sys.stderr,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> | "
        "trace={extra[trace_id]} | "
        "<level>{message}</level>"
    ),
)
logger.add(
    "/tmp/bot_logs.log",
    rotation="5 MB",
    compression="zip",
    level="INFO",
    format=(
        "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
        "{name}:{function} | trace={extra[trace_id]} | {message}"
    ),
)

_DB_RESET_CONFIRMATIONS: dict[int, tuple[str, float]] = {}
_DB_RESET_CONFIRMATION_TTL_SEC = 300
_DB_RESET_LOCK = asyncio.Lock()


async def start_handler(message: Message, session: AsyncSession) -> None:
    tenant = await resolve_tenant_by_bot_token(session, settings.bot_token)
    primary_owner_tg_id = await get_primary_owner_tg_id(session, tenant.id)
    role = UserRole.CLIENT.value
    if primary_owner_tg_id is None and message.from_user.id == settings.owner_id:
        role = UserRole.OWNER.value
    user, membership = await get_or_create_default_tenant_user(
        session,
        tg_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        default_role=role,
        ai_quota=settings.ai_client_start_quota,
    )

    role_value = await get_role_for_user(session, user, tenant.id)
    if await is_user_blocked_in_tenant(session, message.from_user.id, tenant.id) and normalize_role(role_value) != UserRole.OWNER.value:
        await message.answer("⛔ Вы заблокированы.")
        return

    tenant_settings = await get_or_create_tenant_settings(session, user.tenant_id)
    await session.commit()

    logger.info(
        "start_command tenant_slug={} tenant_id={} user_id={} username={} role={} text={!r}",
        tenant.slug,
        tenant.id,
        message.from_user.id,
        message.from_user.username,
        normalize_role(role_value),
        message.text,
    )

    first_name = message.from_user.first_name or "гость"

    # Меню по ролям
    if normalize_role(role_value) == UserRole.OWNER.value:
        menu_rows = tenant_settings.menu_owner or [
            ["📦 Товары", "📊 Склад"],
            ["📋 Заказы", "📈 Статистика"],
            ["✨ AI-Консультант", "🔙 Отмена"],
        ]
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=str(button_text)) for button_text in row] for row in menu_rows],
            resize_keyboard=True,
        )
        text = tenant_settings.welcome_text_owner or f"👑 Привет, владелец {first_name}!\nВыбери действие:"
    
    elif normalize_role(role_value) == UserRole.STAFF.value:
        menu_rows = tenant_settings.menu_staff or [
            ["🛍 Каталог", "📋 Заказы"],
            ["💳 Касса"],
        ]
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=str(button_text)) for button_text in row] for row in menu_rows],
            resize_keyboard=True,
        )
        text = tenant_settings.welcome_text_staff or f"👔 Привет, сотрудник {first_name}!\nТвой рабочий терминал готов."
    else:
        menu_rows = tenant_settings.menu_client or [
            ["🛍 Каталог", "🛒 Корзина"],
            ["📦 Заказы", "✨ AI-Консультант"],
            ["💬 Продавец", "💬 Владелец"],
        ]
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=str(button_text)) for button_text in row] for row in menu_rows],
            resize_keyboard=True,
        )
        text = tenant_settings.welcome_text_client or f"Привет, {first_name}!\nВыбери действие:"

    await message.answer(text, reply_markup=kb)


async def set_staff_handler(message: Message, session: AsyncSession) -> None:
    if not await is_runtime_owner(session, message.from_user.id):
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
    tenant = await resolve_tenant_by_bot_token(session, settings.bot_token)
    membership = await ensure_tenant_membership(session, user, tenant.id, UserRole.CLIENT.value)
    membership.role = UserRole.STAFF.value
    if user.tenant_id is None:
        user.tenant_id = tenant.id
    await sync_user_role_from_memberships(session, user)
    await session.commit()
    logger.info(
        "owner_action action=staff tenant_id=%s actor_tg_id=%s target_tg_id=%s",
        tenant.id,
        message.from_user.id,
        target_tg_id,
    )
    await message.answer(f"✅ Пользователь {target_tg_id} теперь STAFF.")


async def unset_staff_handler(message: Message, session: AsyncSession) -> None:
    if not await is_runtime_owner(session, message.from_user.id):
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
    tenant = await resolve_tenant_by_bot_token(session, settings.bot_token)
    membership = await ensure_tenant_membership(session, user, tenant.id, UserRole.CLIENT.value)
    membership.role = UserRole.CLIENT.value
    if user.tenant_id is None:
        user.tenant_id = tenant.id
    await sync_user_role_from_memberships(session, user)
    await session.commit()
    logger.info(
        "owner_action action=unstaff tenant_id=%s actor_tg_id=%s target_tg_id=%s",
        tenant.id,
        message.from_user.id,
        target_tg_id,
    )
    await message.answer(f"✅ Пользователь {target_tg_id} теперь CLIENT.")


async def reset_db_handler(message: Message, session: AsyncSession) -> None:
    if not await is_runtime_owner(session, message.from_user.id):
        await message.answer("Эта команда доступна только владельцу.")
        return

    confirmation_code = secrets.token_hex(4).upper()
    expires_at = time.time() + _DB_RESET_CONFIRMATION_TTL_SEC
    _DB_RESET_CONFIRMATIONS[message.from_user.id] = (confirmation_code, expires_at)

    await message.answer(
        "⚠️ Будут удалены все пользователи, товары, заказы, корзины, склад и AI-логи.\n"
        f"Для подтверждения в течение 5 минут отправь: /confirm_resetdb {confirmation_code}"
    )


async def confirm_reset_db_handler(message: Message, session: AsyncSession) -> None:
    if not await is_runtime_owner(session, message.from_user.id):
        await message.answer("Эта команда доступна только владельцу.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Используй: /confirm_resetdb <код>")
        return

    expected = _DB_RESET_CONFIRMATIONS.get(message.from_user.id)
    if expected is None:
        await message.answer("Нет активного запроса на очистку. Сначала вызови /resetdb")
        return

    code, expires_at = expected
    if time.time() > expires_at:
        _DB_RESET_CONFIRMATIONS.pop(message.from_user.id, None)
        await message.answer("Код подтверждения истек. Сначала вызови /resetdb заново.")
        return

    if parts[1].strip().upper() != code:
        await message.answer("Неверный код подтверждения.")
        return

    from database.maintenance import reset_database_data

    if _DB_RESET_LOCK.locked():
        await message.answer("Очистка БД уже выполняется. Дождись завершения.")
        return

    async with _DB_RESET_LOCK:
        _DB_RESET_CONFIRMATIONS.pop(message.from_user.id, None)
        await session.rollback()
        await session.close()
        truncated_tables = await reset_database_data()

    await message.answer(
        f"✅ База данных очищена. Обнулено таблиц: {truncated_tables}.\n"
        "Теперь можно начинать с нуля. Для повторной регистрации владельца используй /start."
    )


async def on_startup() -> None:
    logger.info("Инициализация БД…")
    await init_db()
    async with async_session_maker() as session:
        await resolve_tenant_by_bot_token(session, settings.bot_token)
        await session.commit()
    logger.info("БД готова.")


def setup_routers(dp: Dispatcher) -> None:
    dp.include_router(admin_router)
    dp.include_router(admin_orders_router)
    dp.include_router(ai_router)
    dp.include_router(product_router)
    dp.include_router(warehouse_router)  # 👈 НОВЫЙ СКЛАД
    dp.include_router(main_router)
    dp.include_router(client_router)


def setup_error_handlers(dp: Dispatcher) -> None:
    @dp.errors()
    async def _global_errors(event: ErrorEvent):
        exc = event.exception
        if isinstance(exc, TelegramBadRequest) and "message is not modified" in str(exc).lower():
            logger.debug(f"Suppressed harmless TelegramBadRequest: {exc}")
            return
        logger.exception(f"Unhandled dispatcher error: {exc}")


async def main() -> None:
    bot = Bot(token=settings.bot_token)
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)

    db_session_mw = DbSessionMiddleware(session_pool=async_session_maker)
    block_user_mw = BlockUserMiddleware(session_pool=async_session_maker)
    trace_mw = TraceMiddleware()

    # TraceMiddleware — самый первый: устанавливает trace_id до всех остальных
    dp.update.outer_middleware(trace_mw)
    dp.update.middleware(db_session_mw)
    dp.message.middleware(block_user_mw)
    dp.callback_query.middleware(block_user_mw)

    dp.message.register(start_handler, CommandStart())
    dp.message.register(set_staff_handler, Command("staff"))
    dp.message.register(unset_staff_handler, Command("unstaff"))
    dp.message.register(reset_db_handler, Command("resetdb"))
    dp.message.register(confirm_reset_db_handler, Command("confirm_resetdb"))

    setup_routers(dp)
    setup_error_handlers(dp)

    await on_startup()
    logger.info("Запускаю бота…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
