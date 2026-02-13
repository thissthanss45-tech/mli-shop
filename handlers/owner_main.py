"""Основные хэндлеры владельца: меню, отмена, удаление, заказы, статистика."""

import os
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, 
    FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError, TelegramNotFound, TelegramBadRequest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from database.catalog_repo import CatalogRepo
from database.orders_repo import OrdersRepo
from models.catalog import Category, Brand, Product
from models.orders import OrderStatus
from models import User, UserRole
from models.users import normalize_role

from .owner_states import (
    DeleteProductStates,
    DeleteCategoryStates,
    DeleteBrandStates,
    SupportReplyStates,
    OrderHistoryStates,
)
from .owner_keyboards import (
    cancel_kb,
    build_categories_kb,
    build_brands_kb,
)
from .owner_utils import ensure_owner, show_owner_main_menu

main_router = Router(name="owner_main")
logger = logging.getLogger(__name__)

# ==========================================
# 🎥 БЛОК ПРОМО-ВИДЕО
# ==========================================
CACHED_PROMO_ID = None
PROMO_FILE_PATH = "media/promo.mp4"


async def _broadcast_promo_video(bot, user_ids: list[int], video_id: str, kb: InlineKeyboardMarkup) -> int:
    """Рассылка видео через очередь и пул воркеров для высокой нагрузки."""
    if not user_ids:
        return 0

    queue: asyncio.Queue[int] = asyncio.Queue()
    # The queue + worker pool pattern keeps promo blasts fast and non-blocking.
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

@main_router.message(F.from_user.id == int(os.getenv("OWNER_ID")), F.text == "/promo")
async def send_promo_from_server(message: Message, session: AsyncSession):
    global CACHED_PROMO_ID
    if not os.path.exists(PROMO_FILE_PATH):
        await message.answer(f"❌ Файл не найден!\nЗагрузи видео в папку: <code>{PROMO_FILE_PATH}</code>")
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

# ---------- СТАРТ И ОСНОВНОЕ МЕНЮ ----------

@main_router.message(Command("owner"))
async def owner_command_handler(message: Message, session: AsyncSession) -> None:
    if not await ensure_owner(message, session): 
        return
    await show_owner_main_menu(message)

# ---------- УПРАВЛЕНИЕ БАЛЛАМИ ----------

@main_router.message(Command("gift"))
async def owner_gift_quota(message: Message, session: AsyncSession) -> None:
    if not await ensure_owner(message, session): 
        return
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
            await message.answer("❌ Пользователь не найден.")
    except (IndexError, ValueError):
        await message.answer("⚠️ Ошибка формата. Используй: /gift ID СУММА")    


@main_router.message(Command("block"))
async def owner_block_user(message: Message, session: AsyncSession) -> None:
    if not await ensure_owner(message, session):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Используй: /block <telegram_id>")
        return
    target_id = int(parts[1])
    stmt = select(User).where(User.tg_id == target_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        await message.answer("❌ Пользователь не найден.")
        return
    user.is_blocked = True
    await session.commit()
    await message.answer(f"⛔ Пользователь {target_id} заблокирован.")


@main_router.message(Command("unblock"))
async def owner_unblock_user(message: Message, session: AsyncSession) -> None:
    if not await ensure_owner(message, session):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Используй: /unblock <telegram_id>")
        return
    target_id = int(parts[1])
    stmt = select(User).where(User.tg_id == target_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        await message.answer("❌ Пользователь не найден.")
        return
    user.is_blocked = False
    await session.commit()
    await message.answer(f"✅ Пользователь {target_id} разблокирован.")

@main_router.message(F.text == "⬅ Назад")
async def owner_back_to_main(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not await ensure_owner(message, session): 
        return
    await state.clear()
    await show_owner_main_menu(message)

# ---------- ОТМЕНА ----------

async def _send_correct_menu(message: Message, session: AsyncSession):
    # Если Владелец
    if message.from_user.id == settings.owner_id:
        await show_owner_main_menu(message)
        return
    
    # Если Сотрудник
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

@main_router.callback_query(F.data == "owner:cancel")
async def owner_cancel_any_step(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer("✅ Действие отменено.")
    await _send_correct_menu(callback.message, session)

@main_router.message(F.text.in_(["❌ Отмена", "⛔ Отмена", "🔙 Отмена"]))
async def owner_cancel_from_reply(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await message.answer("✅ Действие отменено.")
    await _send_correct_menu(message, session)


# ---------- ПОДДЕРЖКА КЛИЕНТОВ ----------

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
    if message.text in {"⬅ Назад", "🔙 Назад", "❌ Отмена"}:
        await state.clear()
        await _send_correct_menu(message, session)
        return

    data = await state.get_data()
    target_id = data.get("reply_target_id")
    if not target_id:
        await state.clear()
        await _send_correct_menu(message, session)
        return

    await message.bot.send_message(
        chat_id=target_id,
        text=f"💬 Сообщение от поддержки:\n{message.text}",
    )
    await message.answer("✅ Ответ отправлен.")
    await state.clear()
    await _send_correct_menu(message, session)


@main_router.callback_query(F.data.startswith("contact:block:"))
async def support_block_user(callback: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_owner(callback, session):
        return
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
async def support_unblock_user(callback: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_owner(callback, session):
        return
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

# ---------- УДАЛЕНИЕ ТОВАРА ----------

@main_router.message(F.text.in_(["❌ Удалить товар", "🗑 Удалить товар"]))
async def owner_delete_product_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not await ensure_owner(message, session): 
        return
    repo = CatalogRepo(session)
    categories = await repo.list_categories()
    if not categories:
        await message.answer("Категории не найдены.")
        return
    await state.clear()
    await state.set_state(DeleteProductStates.choose_category)
    kb = build_categories_kb(list(categories))
    await message.answer("🗑 Удаление товара\n\nВыбери категорию:", reply_markup=kb)

@main_router.callback_query(DeleteProductStates.choose_category, F.data.startswith("owner:cat:"))
async def owner_delete_choose_category(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    category_id = int(callback.data.split(":")[-1])
    await state.update_data(category_id=category_id)
    repo = CatalogRepo(session)
    brands = await repo.list_brands()
    if not brands:
        await callback.message.edit_text("Бренды не найдены.")
        return
    kb = build_brands_kb(list(brands))
    await state.set_state(DeleteProductStates.choose_brand)
    await callback.message.edit_text("Выбери бренд:", reply_markup=kb)
    await callback.answer()

@main_router.callback_query(DeleteProductStates.choose_brand, F.data.startswith("owner:brand:"))
async def owner_delete_choose_brand(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    brand_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    repo = CatalogRepo(session)
    products = await repo.list_products_by_category_brand(data.get("category_id"), brand_id)
    if not products:
        await callback.message.edit_text("Товары не найдены.")
        return
    kb = InlineKeyboardBuilder()
    for prod in products:
        kb.button(text=f"{prod.title} — {prod.sale_price} ₽", callback_data=f"owner:delprod:{prod.id}")
    kb.button(text="❌ Отмена", callback_data="owner:cancel")
    kb.adjust(1)
    await state.set_state(DeleteProductStates.choose_product)
    await callback.message.edit_text("Выбери товар для удаления:", reply_markup=kb.as_markup())
    await callback.answer()

@main_router.callback_query(DeleteProductStates.choose_product, F.data.startswith("owner:delprod:"))
async def owner_delete_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    product_id = int(callback.data.split(":")[-1])
    await state.update_data(product_id=product_id)
    product = await session.get(Product, product_id)
    if not product:
        await callback.answer("Товар не найден")
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить удаление", callback_data="owner:confirm_delete")
    kb.button(text="❌ Отмена", callback_data="owner:cancel")
    kb.adjust(1)
    await state.set_state(DeleteProductStates.confirm)
    await callback.message.edit_text(f"⚠️ Удалить товар {product.title}?", reply_markup=kb.as_markup())
    await callback.answer()

@main_router.callback_query(DeleteProductStates.confirm, F.data == "owner:confirm_delete")
async def owner_delete_execute(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    repo = CatalogRepo(session)
    await repo.delete_product(data.get("product_id"))
    await session.commit()
    await state.clear()
    await callback.message.edit_text("✅ Товар удалён.")
    await show_owner_main_menu(callback.message)
    await callback.answer()

# ---------- УДАЛЕНИЕ КАТЕГОРИИ ----------

@main_router.message(F.text == "🗑 Удалить категорию")
async def owner_delete_category_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not await ensure_owner(message, session): 
        return
    repo = CatalogRepo(session)
    categories = await repo.list_categories()
    if not categories:
        await message.answer("Нет категорий.")
        return
    kb = InlineKeyboardBuilder()
    for cat in categories:
        kb.button(text=cat.name, callback_data=f"owner:delcat:{cat.id}")
    kb.button(text="❌ Отмена", callback_data="owner:cancel")
    kb.adjust(1)
    await state.clear()
    await state.set_state(DeleteCategoryStates.choose)
    await message.answer("🗑 Удаление категории:", reply_markup=kb.as_markup())

@main_router.callback_query(DeleteCategoryStates.choose, F.data.startswith("owner:delcat:"))
async def owner_delete_category_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    category_id = int(callback.data.split(":")[-1])
    await state.update_data(category_id=category_id)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="owner:confirm_delcat")
    kb.button(text="❌ Отмена", callback_data="owner:cancel")
    kb.adjust(1)
    await state.set_state(DeleteCategoryStates.confirm)
    await callback.message.edit_text("⚠️ Удалить категорию и ВСЕ товары в ней?", reply_markup=kb.as_markup())
    await callback.answer()

@main_router.callback_query(DeleteCategoryStates.confirm, F.data == "owner:confirm_delcat")
async def owner_delete_category_execute(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    repo = CatalogRepo(session)
    await repo.delete_category(data.get("category_id"))
    await session.commit()
    await state.clear()
    await callback.message.edit_text("✅ Категория удалена.")
    await show_owner_main_menu(callback.message)
    await callback.answer()

# ---------- УДАЛЕНИЕ БРЕНДА ----------

@main_router.message(F.text == "🗑 Удалить бренд")
async def owner_delete_brand_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not await ensure_owner(message, session): 
        return
    repo = CatalogRepo(session)
    brands = await repo.list_brands()
    if not brands:
        await message.answer("Нет брендов.")
        return
    kb = InlineKeyboardBuilder()
    for brand in brands:
        kb.button(text=brand.name, callback_data=f"owner:delbrand:{brand.id}")
    kb.button(text="❌ Отмена", callback_data="owner:cancel")
    kb.adjust(1)
    await state.clear()
    await state.set_state(DeleteBrandStates.choose)
    await message.answer("🗑 Удаление бренда:", reply_markup=kb.as_markup())

@main_router.callback_query(DeleteBrandStates.choose, F.data.startswith("owner:delbrand:"))
async def owner_delete_brand_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    brand_id = int(callback.data.split(":")[-1])
    await state.update_data(brand_id=brand_id)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="owner:confirm_delbrand")
    kb.button(text="❌ Отмена", callback_data="owner:cancel")
    kb.adjust(1)
    await state.set_state(DeleteBrandStates.confirm)
    await callback.message.edit_text("⚠️ Удалить бренд и ВСЕ товары в нем?", reply_markup=kb.as_markup())
    await callback.answer()

@main_router.callback_query(DeleteBrandStates.confirm, F.data == "owner:confirm_delbrand")
async def owner_delete_brand_execute(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    repo = CatalogRepo(session)
    await repo.delete_brand(data.get("brand_id"))
    await session.commit()
    await state.clear()
    await callback.message.edit_text("✅ Бренд удалён.")
    await show_owner_main_menu(callback.message)
    await callback.answer()

# ---------- УПРАВЛЕНИЕ ЗАКАЗАМИ ----------

HISTORY_PAGE_SIZE = 20

def _orders_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Активные заказы")],
            [KeyboardButton(text="✅ История заказов")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


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


def _build_history_kb(page: int, total_pages: int, has_filter: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    nav_count = 0
    if total_pages > 1 and page > 1:
        kb.button(text="⬅️ Назад", callback_data=f"orders:history:page:{page-1}")
        nav_count += 1
    if total_pages > 1 and page < total_pages:
        kb.button(text="Вперед ➡️", callback_data=f"orders:history:page:{page+1}")
        nav_count += 1

    kb.button(text="📆 Фильтр по дате", callback_data="orders:history:filter")
    if has_filter:
        kb.button(text="♻️ Сбросить фильтр", callback_data="orders:history:reset")

    layout = []
    if nav_count > 0:
        layout.append(nav_count)
    layout.append(1)
    if has_filter:
        layout.append(1)
    kb.adjust(*layout)
    return kb.as_markup()


async def _render_orders_history(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    page: int,
    edit: bool,
) -> None:
    data = await state.get_data()
    date_str = data.get("history_date")
    start_date = None
    end_date = None

    if date_str:
        try:
            parsed_date = datetime.strptime(date_str, "%d.%m.%Y")
            start_date = datetime(parsed_date.year, parsed_date.month, parsed_date.day)
            end_date = start_date + timedelta(days=1) - timedelta(microseconds=1)
        except ValueError:
            date_str = None
            await state.update_data(history_date=None)

    repo = OrdersRepo(session)
    total_count = await repo.count_orders_by_statuses(
        [OrderStatus.COMPLETED.value],
        start_date=start_date,
        end_date=end_date,
    )
    total_pages = max(1, (total_count + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
    page = max(1, min(page, total_pages))

    orders = []
    if total_count > 0:
        offset = (page - 1) * HISTORY_PAGE_SIZE
        orders = await repo.get_orders_with_items_by_statuses_paginated(
            [OrderStatus.COMPLETED.value],
            limit=HISTORY_PAGE_SIZE,
            offset=offset,
            start_date=start_date,
            end_date=end_date,
        )

    filter_label = date_str if date_str else "без фильтра"
    text_parts = [
        "✅ <b>История выполненных заказов</b>",
        f"Фильтр по дате: <b>{filter_label}</b>",
        f"Страница {page}/{total_pages} | Всего: {total_count}",
    ]

    if not orders:
        text_parts.append("\n✅ Выполненных заказов не найдено.")
    else:
        for order in orders:
            lines_list = []
            if not order.items:
                lines_list.append("⚠️ <i>Ошибка: Заказ пуст</i>")
            else:
                for item in order.items:
                    brand = item.product.brand.name if (item.product and item.product.brand) else "Без бренда"
                    title = item.product.title if item.product else "ТОВАР УДАЛЁН"
                    sku = item.product.sku if (item.product and item.product.sku) else None
                    price_fmt = f"{item.sale_price:g}"
                    sku_line = f"   SKU: {sku}\n" if sku else ""
                    lines_list.append(
                        f"▫️ <b>{brand} | {title}</b>\n"
                        f"{sku_line}"
                        f"   Размер: {item.size} | {item.quantity} шт. | {price_fmt} ₽"
                    )

            items_text = "\n".join(lines_list)
            date_fmt = order.created_at.strftime('%d.%m.%Y')
            total_fmt = f"{order.total_price:g}"
            text_parts.append(
                "\n"
                f"✅ <b>Заказ #{order.id} от {date_fmt}</b>\n"
                f"👤 {order.full_name}\n"
                f"📱 <code>{order.phone}</code>\n"
                f"💰 Сумма: <b>{total_fmt} ₽</b>\n"
                f"<b>Состав заказа:</b>\n{items_text}"
            )

    text = "\n".join(text_parts)
    reply_markup = _build_history_kb(page, total_pages, has_filter=bool(date_str))

    if edit:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")


@main_router.message(F.text == "📋 Заказы")
async def owner_orders_menu(message: Message, session: AsyncSession) -> None:
    if not await _require_owner_or_staff(message, session):
        return
    await message.answer("Выберите раздел заказов:", reply_markup=_orders_menu_kb())


@main_router.message(F.text == "📋 Активные заказы")
async def owner_active_orders(message: Message, session: AsyncSession) -> None:
    if not await _require_owner_or_staff(message, session):
        return

    is_owner = message.from_user.id == settings.owner_id

    repo = OrdersRepo(session)
    if is_owner:
        orders = await repo.get_orders_with_items_by_statuses(
            [OrderStatus.NEW.value, OrderStatus.PROCESSING.value]
        )
    else:
        orders = await repo.get_orders_with_items_by_statuses(
            [OrderStatus.NEW.value, OrderStatus.PROCESSING.value]
        )

    if not orders:
        await message.answer("✅ Активных заказов нет.")
        return

    await message.answer(f"📋 <b>Активные заказы: {len(orders)} шт.</b>", parse_mode="HTML")

    for order in orders:
        lines_list = []
        if not order.items:
            lines_list.append("⚠️ <i>Ошибка: Заказ пуст</i>")
        else:
            for item in order.items:
                brand = item.product.brand.name if (item.product and item.product.brand) else "Без бренда"
                title = item.product.title if item.product else "ТОВАР УДАЛЁН"
                sku = item.product.sku if (item.product and item.product.sku) else None
                price_fmt = f"{item.sale_price:g}"
                sku_line = f"   SKU: {sku}\n" if sku else ""
                lines_list.append(
                    f"▫️ <b>{brand} | {title}</b>\n"
                    f"{sku_line}"
                    f"   Размер: {item.size} | {item.quantity} шт. | {price_fmt} ₽"
                )

        items_text = "\n".join(lines_list)
        total_fmt = f"{order.total_price:g}"
        card_text = (
            f"🆔 <b>Заказ #{order.id}</b>\n"
            f"👤 {order.full_name}\n"
            f"📱 <code>{order.phone}</code>\n"
            f"💰 Сумма: <b>{total_fmt} ₽</b>\n"
            f"<b>Состав заказа:</b>\n{items_text}"
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Выполнен", callback_data=f"order:done:{order.id}")
        kb.button(text="❌ Отменить", callback_data=f"order:cancel:{order.id}")
        kb.adjust(2)
        await message.answer(card_text, reply_markup=kb.as_markup(), parse_mode="HTML")


@main_router.message(F.text == "✅ История заказов")
async def owner_orders_history(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not await _require_owner_or_staff(message, session):
        return
    await _render_orders_history(message, session, state, page=1, edit=False)


@main_router.callback_query(F.data.startswith("orders:history:"))
async def owner_orders_history_cb(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not await _require_owner_or_staff_cb(callback, session):
        return

    parts = callback.data.split(":")
    action = parts[2] if len(parts) > 2 else ""

    if action == "page" and len(parts) == 4 and parts[3].isdigit():
        page = int(parts[3])
        await _render_orders_history(callback.message, session, state, page=page, edit=True)
        await callback.answer()
        return

    if action == "filter":
        await state.set_state(OrderHistoryStates.waiting_for_date)
        await callback.message.answer("Введите дату в формате ДД.ММ.ГГГГ")
        await callback.answer()
        return

    if action == "reset":
        await state.update_data(history_date=None)
        await _render_orders_history(callback.message, session, state, page=1, edit=True)
        await callback.answer()
        return

    await callback.answer()


@main_router.message(OrderHistoryStates.waiting_for_date)
async def owner_orders_history_set_date(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not await _require_owner_or_staff(message, session):
        return

    text = (message.text or "").strip()
    if text in {"❌ Отмена", "🔙 Назад"}:
        await state.set_state(None)
        await _render_orders_history(message, session, state, page=1, edit=False)
        return

    try:
        datetime.strptime(text, "%d.%m.%Y")
    except ValueError:
        await message.answer("Неверный формат. Введите дату как ДД.ММ.ГГГГ, например 13.02.2026.")
        return

    await state.update_data(history_date=text)
    await state.set_state(None)
    await _render_orders_history(message, session, state, page=1, edit=False)

@main_router.callback_query(F.data.startswith("order:done:"))
async def owner_order_done(callback: CallbackQuery, session: AsyncSession) -> None:
    order_id = int(callback.data.split(":")[2])
    repo = OrdersRepo(session)
    if await repo.update_order_status(order_id, OrderStatus.COMPLETED.value):
        await session.commit()
        await callback.message.edit_text(f"✅ Заказ #{order_id} выполнен.")
    else:
        await callback.answer("Ошибка")

@main_router.callback_query(F.data.startswith("order:cancel:"))
async def owner_order_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    order_id = int(callback.data.split(":")[2])
    repo = OrdersRepo(session)
    if await repo.cancel_order(order_id):
        await session.commit()
        await callback.message.edit_text(f"❌ Заказ #{order_id} отменен, товары возвращены.")
    else:
        await callback.answer("Ошибка")


@main_router.message(F.text == "💳 Касса")
async def staff_cash_menu(message: Message, session: AsyncSession) -> None:
    stmt = select(User).where(User.tg_id == message.from_user.id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user or normalize_role(user.role) != UserRole.STAFF.value:
        await message.answer("⛔ Только для персонала.")
        return

    repo = OrdersRepo(session)
    now = datetime.utcnow()
    day_start = datetime(now.year, now.month, now.day)
    week_start = now - timedelta(days=7)

    day_stats = await repo.get_stats_for_period(day_start, now)
    week_stats = await repo.get_stats_for_period(week_start, now)

    text = (
        "💳 <b>Касса</b>\n\n"
        f"Сегодня: <b>{day_stats['revenue']:,.0f} ₽</b>\n"
        f"За 7 дней: <b>{week_stats['revenue']:,.0f} ₽</b>"
    )
    await message.answer(text, parse_mode="HTML")

# ---------- СТАТИСТИКА ----------

async def _render_stats_menu(message: Message, edit: bool) -> None:
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 За сегодня", callback_data="stats:day")
    kb.button(text="🗓 За 7 дней", callback_data="stats:week")
    kb.button(text="📆 За 30 дней", callback_data="stats:month")
    kb.button(text="🏆 Топ товаров", callback_data="stats:top")
    kb.button(text="❌ Закрыть", callback_data="owner:cancel")
    kb.adjust(1)

    if edit:
        await message.edit_text(
            "📊 <b>Панель аналитики:</b>",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "📊 <b>Панель аналитики:</b>",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )

@main_router.message(F.text == "📈 Статистика")
async def owner_stats_menu(message: Message, session: AsyncSession) -> None:
    if not await ensure_owner(message, session): 
        return
    await _render_stats_menu(message, edit=False)

@main_router.callback_query(F.data.startswith("stats:"))
async def owner_stats_show(callback: CallbackQuery, session: AsyncSession) -> None:
    if not await ensure_owner(callback, session):
        return
    period = callback.data.split(":")[1]
    repo = OrdersRepo(session)
    now = datetime.utcnow()

    if period == "day":
        start_date = datetime(now.year, now.month, now.day)
        period_name = "сегодня"
    elif period == "week":
        start_date = now - timedelta(days=7)
        period_name = "7 дней"
    elif period == "month":
        start_date = now - timedelta(days=30)
        period_name = "30 дней"
    elif period == "top":
        top_list = await repo.get_top_products(limit=5)
        if not top_list:
            await callback.message.edit_text("Нет данных для топа.")
            return
        text = "🏆 <b>Топ-5:</b>\n\n"
        for idx, (title, qty) in enumerate(top_list, 1):
            text += f"{idx}. <b>{title}</b> — {qty} шт.\n"
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 Назад", callback_data="stats:menu")
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        return
    elif period == "menu":
        await _render_stats_menu(callback.message, edit=True)
        return
    else:
        await callback.message.delete()
        return

    stats = await repo.get_stats_for_period(start_date, now)
    text = (
        f"📊 <b>Отчет за {period_name}:</b>\n\n"
        f"📦 Заказов: <b>{stats['count']}</b>\n"
        f"💰 Выручка: <b>{stats['revenue']} ₽</b>\n"
        f"💵 Маржинальная прибыль: <b>{stats['profit']} ₽</b>\n"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data="stats:menu")
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")