from __future__ import annotations

import asyncio
import os

from aiogram import F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramForbiddenError, TelegramNotFound, TelegramBadRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import User, UserRole
from models.users import normalize_role
from ..owner_states import SupportReplyStates
from ..owner_utils import ensure_owner, owner_only, show_owner_main_menu
from .common import main_router, logger, _send_correct_menu, _is_owner_or_staff

CACHED_PROMO_ID = None
PROMO_FILE_PATH = "media/promo.mp4"


async def _broadcast_promo_video(bot, user_ids: list[int], video_id: str, kb: InlineKeyboardMarkup) -> int:
    if not user_ids:
        return 0

    queue: asyncio.Queue[int] = asyncio.Queue()
    for uid in user_ids:
        queue.put_nowait(uid)

    worker_count = min(16, len(user_ids)) or 1
    sent = 0
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal sent
        while True:
            user_id = await queue.get()
            delivered = False
            try:
                await bot.send_video(
                    chat_id=user_id,
                    video=video_id,
                    caption="🔥 Новая коллекция уже доступна! Заходите в витрину.",
                    reply_markup=kb,
                )
                delivered = True
            except (TelegramForbiddenError, TelegramNotFound) as exc:
                logger.info("Promo skipped for %s: %s", user_id, exc)
            except TelegramBadRequest as exc:
                logger.warning("Promo bad request for %s: %s", user_id, exc)
            except Exception as exc:
                logger.error("Promo broadcast error for %s: %s", user_id, exc)
            finally:
                if delivered:
                    async with lock:
                        sent += 1
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
    await queue.join()
    for task in workers:
        task.cancel()
    return sent


@main_router.message(Command("promo"))
@owner_only
async def send_promo_from_server(message: Message, session: AsyncSession):
    global CACHED_PROMO_ID
    if not os.path.exists(PROMO_FILE_PATH):
        await message.answer(f"⚠️ Файл не найден!\nЗагрузи видео в папку: <code>{PROMO_FILE_PATH}</code>")
        return

    status_msg = await message.answer("🚀 Заряжаю промо-ролик с сервера...")

    video_to_send = CACHED_PROMO_ID
    if not video_to_send:
        video_input = FSInputFile(PROMO_FILE_PATH)
        sent_msg = await message.answer_video(video_input, caption="✅ Исходник загружен. Начинаю рассылку...")
        CACHED_PROMO_ID = sent_msg.video.file_id
        video_to_send = CACHED_PROMO_ID
    else:
        await message.answer_video(video_to_send, caption="⚡️ Использую кэш (мгновенно).")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Перейти к покупкам", callback_data="catalog_start")]
    ])

    users_result = await session.execute(select(User.tg_id))
    users = [uid for uid in users_result.scalars().all() if uid and uid != message.from_user.id]

    if not users:
        await status_msg.edit_text("⚠️ Нет получателей для рассылки.")
        return

    await status_msg.edit_text(f"🚀 Рассылка запущена по {len(users)} пользователям...")

    sent = await _broadcast_promo_video(message.bot, users, video_to_send, kb)

    await message.answer(f"🏁 Рассылка завершена! Доставлено: {sent} из {len(users)}.")


@main_router.message(Command("owner"))
@owner_only
async def owner_command_handler(message: Message, session: AsyncSession) -> None:
    await show_owner_main_menu(message)


@main_router.message(Command("gift"))
@owner_only
async def owner_gift_quota(message: Message, session: AsyncSession) -> None:
    try:
        parts = message.text.split()
        target_id = int(parts[1])
        amount = int(parts[2])

        stmt = select(User).where(User.tg_id == target_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            user.ai_quota += amount
            await session.commit()
            await message.answer(f"✅ Пользователю {target_id} начислено {amount} запросов.\nТекущий баланс: {user.ai_quota}")
        else:
            await message.answer("⚠️ Пользователь не найден.")
    except (IndexError, ValueError):
        await message.answer("⚠️ Ошибка формата. Используй: /gift ID СУММА")


@main_router.message(Command("block"))
@owner_only
async def owner_block_user(message: Message, session: AsyncSession) -> None:
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Используй: /block <telegram_id>")
        return
    target_id = int(parts[1])
    stmt = select(User).where(User.tg_id == target_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        await message.answer("⚠️ Пользователь не найден.")
        return
    user.is_blocked = True
    await session.commit()
    await message.answer(f"⛔ Пользователь {target_id} заблокирован.")


@main_router.message(Command("unblock"))
@owner_only
async def owner_unblock_user(message: Message, session: AsyncSession) -> None:
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Используй: /unblock <telegram_id>")
        return
    target_id = int(parts[1])
    stmt = select(User).where(User.tg_id == target_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        await message.answer("⚠️ Пользователь не найден.")
        return
    user.is_blocked = False
    await session.commit()
    await message.answer(f"✅ Пользователь {target_id} разблокирован.")


@main_router.message(F.text == "⬅ Назад")
@owner_only
async def owner_back_to_main(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await show_owner_main_menu(message)


@main_router.message(Command("add_owner"))
@owner_only
async def owner_add_owner(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Используй: /add_owner <telegram_id>")
        return

    target_id = int(parts[1])
    stmt = select(User).where(User.tg_id == target_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        await message.answer("⚠️ Пользователь не найден в БД. Пусть сначала напишет боту /start.")
        return

    user.role = UserRole.OWNER.value
    await session.commit()
    await message.answer(f"✅ Пользователь {target_id} назначен владельцем.")


@main_router.message(Command("remove_owner"))
@owner_only
async def owner_remove_owner(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Используй: /remove_owner <telegram_id>")
        return

    target_id = int(parts[1])
    if target_id == settings.owner_id:
        await message.answer("⛔ Нельзя снять роль с главного владельца из ENV OWNER_ID.")
        return

    stmt = select(User).where(User.tg_id == target_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        await message.answer("⚠️ Пользователь не найден в БД.")
        return

    if normalize_role(user.role) != UserRole.OWNER.value:
        await message.answer("ℹ️ У пользователя нет роли владельца.")
        return

    user.role = UserRole.CLIENT.value
    await session.commit()
    await message.answer(f"✅ Роль владельца снята с {target_id}.")


@main_router.callback_query(F.data == "owner:cancel")
async def owner_cancel_any_step(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer("✅ Действие отменено.")
    await _send_correct_menu(callback.message, session)


@main_router.message(F.text.in_(["↩️ Назад", "↩️ Отмена", "⛔ Отмена", "🔙 Отмена", "Отмена"]))
async def owner_cancel_from_reply(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await message.answer("✅ Действие отменено.")
    await _send_correct_menu(message, session)


@main_router.callback_query(F.data.startswith("contact:reply:"))
async def support_reply_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not await _is_owner_or_staff(callback.from_user.id, session):
        await callback.answer("⛔ Только для персонала.", show_alert=True)
        return

    target_id = int(callback.data.split(":")[2])
    await state.update_data(reply_target_id=target_id)
    await state.set_state(SupportReplyStates.waiting_for_reply)

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Назад")]],
        resize_keyboard=True,
    )
    await callback.message.answer(f"Введите ответ для клиента {target_id}:", reply_markup=kb)
    await callback.answer()


@main_router.message(SupportReplyStates.waiting_for_reply)
async def support_reply_send(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.text in {"⬅ Назад", "🔙 Назад", "↩️ Назад", "↩️ Отмена", "Отмена"}:
        await state.clear()
        await _send_correct_menu(message, session)
        return

    data = await state.get_data()
    target_id = data.get("reply_target_id")
    if not target_id:
        await state.clear()
        await _send_correct_menu(message, session)
        return

    prefix = "💬 Сообщение от поддержки:"
    if message.text:
        await message.bot.send_message(chat_id=target_id, text=f"{prefix}\n{message.text}")
    else:
        await message.bot.send_message(chat_id=target_id, text=prefix)
        await message.bot.copy_message(
            chat_id=target_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    await message.answer("✅ Ответ отправлен.")
    await state.clear()
    await _send_correct_menu(message, session)


@main_router.callback_query(F.data.startswith("contact:block:"))
@owner_only
async def support_block_user(callback: CallbackQuery, session: AsyncSession) -> None:
    target_id = int(callback.data.split(":")[2])
    stmt = select(User).where(User.tg_id == target_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    user.is_blocked = True
    await session.commit()
    await callback.message.answer(f"⛔ Пользователь {target_id} заблокирован.")
    await callback.answer()


@main_router.callback_query(F.data.startswith("contact:unblock:"))
@owner_only
async def support_unblock_user(callback: CallbackQuery, session: AsyncSession) -> None:
    target_id = int(callback.data.split(":")[2])
    stmt = select(User).where(User.tg_id == target_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    user.is_blocked = False
    await session.commit()
    await callback.message.answer(f"✅ Пользователь {target_id} разблокирован.")
    await callback.answer()
