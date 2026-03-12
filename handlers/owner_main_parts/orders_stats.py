from __future__ import annotations

import calendar
from decimal import Decimal
from datetime import datetime, timedelta
from html import escape

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.dispatcher.event.bases import SkipHandler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.orders_repo import OrdersRepo
from models import User, UserRole
from models.orders import OrderStatus
from utils.tenants import get_runtime_tenant_role_for_tg_id
from ..owner_states import OrderHistoryStates
from ..owner_utils import owner_only
from utils.admin_kb import build_active_order_kb
from .common import (
    main_router,
    logger,
    _require_owner_or_staff,
    _require_owner_or_staff_cb,
    _send_correct_menu,
    _is_owner_or_staff,
)

HISTORY_PAGE_SIZE = 4
STATS_MIN_YEAR = 2026
STATS_MAX_YEAR = 2099
STATS_YEAR_PAGE_SIZE = 9


def _orders_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Активные заказы")],
            [KeyboardButton(text="✅ История заказов")],
            [KeyboardButton(text="🔙 Назад")],
        ],
        resize_keyboard=True,
    )


def _build_history_kb(page: int, total_pages: int, has_filter: bool, filter_label: str = "") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if total_pages > 1 and page > 1:
        kb.button(text="⬅️ Назад", callback_data=f"orders:history:page:{page - 1}")
    if total_pages > 1 and page < total_pages:
        kb.button(text="Вперед ➡️", callback_data=f"orders:history:page:{page + 1}")

    if filter_label:
        kb.button(text=f"📅 {filter_label}", callback_data="orders:history:filter")
    else:
        kb.button(text="📆 Фильтр по дате", callback_data="orders:history:filter")
    if has_filter:
        kb.button(text="♻️ Сбросить фильтр", callback_data="orders:history:reset")

    return kb.as_markup()


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    new_month = month + delta
    new_year = year
    while new_month < 1:
        new_month += 12
        new_year -= 1
    while new_month > 12:
        new_month -= 12
        new_year += 1
    return new_year, new_month


def _build_calendar_kb(year: int, month: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    prev_year, prev_month = _shift_month(year, month, -1)
    next_year, next_month = _shift_month(year, month, 1)
    header = f"{month:02d}.{year}"

    kb.row(
        InlineKeyboardButton(text="⬅️", callback_data=f"orders:history:cal:ym:{prev_year}-{prev_month:02d}"),
        InlineKeyboardButton(text=header, callback_data="orders:history:cal:noop"),
        InlineKeyboardButton(text="➡️", callback_data=f"orders:history:cal:ym:{next_year}-{next_month:02d}"),
    )

    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    kb.row(*[InlineKeyboardButton(text=d, callback_data="orders:history:cal:noop") for d in weekdays])

    cal = calendar.Calendar(firstweekday=0)
    for week in cal.monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text="·", callback_data="orders:history:cal:noop"))
            else:
                row.append(
                    InlineKeyboardButton(
                        text=str(day),
                        callback_data=f"orders:history:cal:day:{year}-{month:02d}-{day:02d}",
                    )
                )
        kb.row(*row)

    kb.row(InlineKeyboardButton(text="↩️ Назад", callback_data="orders:history:cal:close"))
    return kb.as_markup()


async def _render_orders_history(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    page: int,
    edit: bool,
    requester_user_id: int | None = None,
) -> None:
    actor_id = requester_user_id if requester_user_id is not None else message.from_user.id
    role = await get_runtime_tenant_role_for_tg_id(session, actor_id)
    is_owner = role == UserRole.OWNER.value

    now_dt = datetime.now()
    today_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)

    data = await state.get_data()
    date_str = data.get("history_date")

    if date_str:
        try:
            picked = datetime.strptime(date_str, "%d.%m.%Y")
            start_date = picked.replace(hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            start_date = today_start
            date_str = start_date.strftime("%d.%m.%Y")
            await state.update_data(history_date=date_str)
    else:
        start_date = today_start
        date_str = start_date.strftime("%d.%m.%Y")
        await state.update_data(history_date=date_str)

    end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)

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

    today_completed_orders = await repo.get_orders_with_items_by_statuses(
        [OrderStatus.COMPLETED.value],
        start_date=start_date,
        end_date=end_date,
    )

    day_revenue = Decimal("0")
    day_profit = Decimal("0")
    for order in today_completed_orders:
        day_revenue += Decimal(order.total_price or 0)
        for item in order.items:
            if not item.product:
                continue
            sale_price = Decimal(item.sale_price or 0)
            purchase_price = Decimal(item.product.purchase_price or 0)
            day_profit += (sale_price - purchase_price) * item.quantity

    date_str = start_date.strftime("%d.%m.%Y")
    is_today = start_date.date() == today_start.date()
    report_title = "Отчет за сегодня" if is_today else "Отчет за день"

    report_lines = [
        f"📅 <b>{report_title} ({date_str}):</b>",
        f"💰 Выручка: <b>{day_revenue:.2f}₽</b>",
    ]
    if is_owner:
        report_lines.append(f"📈 Чистая прибыль: <b>{day_profit:.2f}₽</b>")
    report_lines.extend([
        "➖➖➖➖➖➖➖➖",
        "📦 <b>Список заказов:</b>",
        f"Страница {page}/{total_pages} | Всего: {total_count}",
    ])
    text = "\n".join(report_lines)

    data = await state.get_data()
    old_ids = data.get("history_msg_ids", [])
    current_msg_id = getattr(message, "message_id", None)
    if old_ids:
        for msg_id in old_ids:
            if current_msg_id and msg_id == current_msg_id:
                continue
            try:
                await message.bot.delete_message(chat_id=message.chat.id, message_id=msg_id)
            except Exception:
                continue
        await state.update_data(history_msg_ids=[])

    reply_markup = _build_history_kb(page, total_pages, has_filter=not is_today, filter_label=date_str)

    if edit:
        try:
            await message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                logger.warning("History message not modified; edit skipped")
            else:
                raise
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)

    if not orders:
        await message.answer("✅ За сегодня выполненных заказов не найдено.")
        await state.update_data(history_msg_ids=[])
        return

    sent_ids: list[int] = []
    for order in orders:
        lines_list = []
        if not order.items:
            lines_list.append("⚠️ <i>Ошибка: Заказ пуст</i>")
        else:
            for item in order.items:
                brand = item.product.brand.name if (item.product and item.product.brand) else "Без бренда"
                title = item.product.title if item.product else "ТОВАР УДАЛЁН"
                price_fmt = f"{item.sale_price:g}"
                lines_list.append(
                    f"▫️ <b>{brand} | {title}</b>\n"
                    f"   Размер: {item.size} | {item.quantity} шт. | {price_fmt} ₽"
                )

        items_text = "\n".join(lines_list)
        date_fmt = order.created_at.strftime('%d.%m.%Y %H:%M')
        total_fmt = f"{order.total_price:g}"
        card_text = (
            f"✅ <b>Заказ #{order.id} от {date_fmt}</b>\n"
            f"👤 {escape(order.full_name or '')}\n"
            f"📱 <code>{escape(order.phone or '')}</code>\n"
            f"💰 Сумма: <b>{total_fmt} ₽</b>\n"
            f"<b>Состав заказа:</b>\n{items_text}"
        )
        kb = InlineKeyboardBuilder()
        for item in order.items:
            if item.product and item.product.sku:
                kb.button(text=f"📦 {item.product.sku}", callback_data=f"prod:0:0:{item.product.id}")
        kb.adjust(1)
        markup = kb.as_markup() if kb.buttons else None
        sent = await message.answer(card_text, parse_mode="HTML", reply_markup=markup)
        sent_ids.append(sent.message_id)

    await state.update_data(history_msg_ids=sent_ids)


@main_router.message(F.text == "📋 Заказы")
async def owner_orders_menu(message: Message, session: AsyncSession) -> None:
    if not await _require_owner_or_staff(message, session):
        return
    await message.answer("Выберите раздел заказов:", reply_markup=_orders_menu_kb())


@main_router.message(F.text == "📋 Активные заказы")
async def owner_active_orders(message: Message, session: AsyncSession) -> None:
    if not await _require_owner_or_staff(message, session):
        return

    repo = OrdersRepo(session)
    orders = await repo.get_orders_with_items_by_statuses([OrderStatus.NEW.value, OrderStatus.PROCESSING.value])

    if not orders:
        await message.answer("✅ Активных заказов нет.")
        return

    db_user_ids = {order.user_id for order in orders}
    users_map: dict[int, tuple[int, str | None]] = {}
    if db_user_ids:
        users_result = await session.execute(select(User.id, User.tg_id, User.username).where(User.id.in_(db_user_ids)))
        users_map = {uid: (tg_id, username) for uid, tg_id, username in users_result.all()}

    await message.answer(f"📋 <b>Активные заказы: {len(orders)} шт.</b>", parse_mode="HTML")

    for order in orders:
        lines_list = []
        if not order.items:
            lines_list.append("⚠️ <i>Ошибка: Заказ пуст</i>")
        else:
            for item in order.items:
                brand = item.product.brand.name if (item.product and item.product.brand) else "Без бренда"
                title = item.product.title if item.product else "ТОВАР УДАЛЁН"
                price_fmt = f"{item.sale_price:g}"
                lines_list.append(
                    f"▫️ <b>{brand} | {title}</b>\n"
                    f"   Размер: {item.size} | {item.quantity} шт. | {price_fmt} ₽"
                )

        items_text = "\n".join(lines_list)
        total_fmt = f"{order.total_price:g}"
        safe_full_name = escape(order.full_name or "Клиент")
        safe_phone = escape(order.phone or "—")
        card_text = (
            f"🆔 <b>Заказ #{order.id}</b>\n"
            f"👤 {safe_full_name}\n"
            f"📱 <code>{safe_phone}</code>\n"
            f"💰 Сумма: <b>{total_fmt} ₽</b>\n"
            f"<b>Состав заказа:</b>\n{items_text}"
        )
        sku_items: list[tuple[str, int]] = []
        for item in order.items:
            if item.product and item.product.sku:
                sku_items.append((item.product.sku, item.product.id))

        user_info = users_map.get(order.user_id)
        user_tg_id = user_info[0] if user_info else None
        username = user_info[1] if user_info else None

        is_web_order = username == "web_storefront"
        if user_tg_id and not is_web_order:
            markup = build_active_order_kb(order.id, user_tg_id, sku_items)
        else:
            kb = InlineKeyboardBuilder()
            for sku, product_id in sku_items:
                kb.button(text=f"📦 {sku}", callback_data=f"prod:0:0:{product_id}")
            kb.button(text="✅ Выполнен", callback_data=f"order:done:{order.id}")
            kb.button(text="🗑 Отменить", callback_data=f"order:cancel:{order.id}")
            kb.adjust(2)
            markup = kb.as_markup()

        try:
            await message.answer(card_text, reply_markup=markup, parse_mode="HTML")
        except TelegramBadRequest as exc:
            fallback_markup = markup
            if user_tg_id and not is_web_order and "BUTTON_USER_PRIVACY_RESTRICTED" in str(exc):
                fallback_markup = build_active_order_kb(order.id, user_tg_id, sku_items, include_profile_button=False)
            fallback_text = (
                f"Заказ #{order.id}\n"
                f"Клиент: {order.full_name}\n"
                f"Телефон: {order.phone}\n"
                f"Сумма: {total_fmt} ₽\n"
                f"Состав заказа:\n{items_text}"
            )
            await message.answer(fallback_text, reply_markup=fallback_markup)


@main_router.message(F.text == "✅ История заказов")
async def owner_orders_history(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not await _require_owner_or_staff(message, session):
        return
    await _render_orders_history(message, session, state, page=1, edit=False, requester_user_id=message.from_user.id)


@main_router.message(F.text.in_(["🔙 Назад", "⬅ Назад"]))
async def owner_orders_back_to_main_menu(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not await _is_owner_or_staff(message.from_user.id, session):
        raise SkipHandler()
    await state.clear()
    await _send_correct_menu(message, session)


@main_router.callback_query(F.data.startswith("orders:history:") & ~F.data.startswith("orders:history:cal:"))
async def owner_orders_history_cb(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not await _require_owner_or_staff_cb(callback, session):
        return

    parts = callback.data.split(":")
    action = parts[2] if len(parts) > 2 else ""

    if action == "page" and len(parts) == 4 and parts[3].isdigit():
        page = int(parts[3])
        await _render_orders_history(callback.message, session, state, page=page, edit=True, requester_user_id=callback.from_user.id)
        await callback.answer()
        return

    if action == "filter":
        now = datetime.utcnow()
        await callback.message.answer("Выберите дату:", reply_markup=_build_calendar_kb(now.year, now.month))
        await callback.answer()
        return

    if action == "reset":
        today_str = datetime.utcnow().strftime("%d.%m.%Y")
        await state.update_data(history_date=today_str)
        await _render_orders_history(callback.message, session, state, page=1, edit=True, requester_user_id=callback.from_user.id)
        await callback.answer()
        return

    await callback.answer()


@main_router.callback_query(F.data.startswith("orders:history:cal:"))
async def owner_orders_history_calendar(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not await _require_owner_or_staff_cb(callback, session):
        return

    parts = callback.data.split(":")
    action = parts[3] if len(parts) > 3 else ""

    if action == "noop":
        await callback.answer()
        return

    if action == "close":
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.answer()
        return

    if action == "ym" and len(parts) == 5:
        try:
            year_str, month_str = parts[4].split("-")
            year = int(year_str)
            month = int(month_str)
        except ValueError:
            await callback.answer()
            return
        await callback.message.edit_reply_markup(reply_markup=_build_calendar_kb(year, month))
        await callback.answer()
        return

    if action == "day" and len(parts) == 5:
        try:
            year_str, month_str, day_str = parts[4].split("-")
            picked = datetime(int(year_str), int(month_str), int(day_str))
        except ValueError:
            await callback.answer()
            return
        await state.update_data(history_date=picked.strftime("%d.%m.%Y"))
        await _render_orders_history(callback.message, session, state, page=1, edit=True, requester_user_id=callback.from_user.id)
        await callback.answer()
        return

    await callback.answer()


@main_router.message(OrderHistoryStates.waiting_for_date)
async def owner_orders_history_set_date(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not await _require_owner_or_staff(message, session):
        return

    text = (message.text or "").strip()
    if text in {"↩️ Назад", "🔙 Назад", "⬅ Назад", "Отмена"}:
        await state.set_state(None)
        await _render_orders_history(message, session, state, page=1, edit=False, requester_user_id=message.from_user.id)
        return

    try:
        datetime.strptime(text, "%d.%m.%Y")
    except ValueError:
        await message.answer("Неверный формат. Введите дату как ДД.ММ.ГГГГ, например 13.02.2026.")
        return

    await state.update_data(history_date=text)
    await state.set_state(None)
    await _render_orders_history(message, session, state, page=1, edit=False, requester_user_id=message.from_user.id)


@main_router.callback_query(F.data.startswith("order:done:"))
async def owner_order_done(callback: CallbackQuery, session: AsyncSession) -> None:
    if not await _require_owner_or_staff_cb(callback, session):
        return
    order_id = int(callback.data.split(":")[2])
    repo = OrdersRepo(session)
    if await repo.update_order_status(order_id, OrderStatus.COMPLETED.value):
        await session.commit()
        await callback.message.edit_text(f"✅ Заказ #{order_id} выполнен.")
    else:
        await callback.answer("Ошибка")


@main_router.callback_query(F.data.startswith("order:cancel:"))
async def owner_order_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    if not await _require_owner_or_staff_cb(callback, session):
        return
    order_id = int(callback.data.split(":")[2])
    repo = OrdersRepo(session)
    if await repo.cancel_order(order_id):
        await session.commit()
        await callback.message.edit_text(f"🗑 Заказ #{order_id} отменен, товары возвращены.")
    else:
        await callback.answer("Ошибка")


@main_router.message(F.text == "💳 Касса")
async def staff_cash_menu(message: Message, session: AsyncSession) -> None:
    if not await _require_owner_or_staff(message, session):
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


def _normalize_stats_year_page_start(start_year: int) -> int:
    upper_start = max(STATS_MIN_YEAR, STATS_MAX_YEAR - STATS_YEAR_PAGE_SIZE + 1)
    return max(STATS_MIN_YEAR, min(start_year, upper_start))


def _build_stats_calendar_mode_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 По дню", callback_data="stats:cal:mode:day")
    kb.button(text="🗓 По месяцу", callback_data="stats:cal:mode:month")
    kb.button(text="📆 По году", callback_data="stats:cal:mode:year")
    kb.button(text="🔙 Назад", callback_data="stats:menu")
    kb.adjust(1)
    return kb.as_markup()


def _build_stats_years_kb(mode: str, start_year: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    start_year = _normalize_stats_year_page_start(start_year)

    years = [
        year for year in range(start_year, start_year + STATS_YEAR_PAGE_SIZE)
        if STATS_MIN_YEAR <= year <= STATS_MAX_YEAR
    ]
    for year in years:
        kb.button(text=str(year), callback_data=f"stats:cal:year:{mode}:{year}")

    prev_start = _normalize_stats_year_page_start(start_year - STATS_YEAR_PAGE_SIZE)
    next_start = _normalize_stats_year_page_start(start_year + STATS_YEAR_PAGE_SIZE)
    kb.button(text="⬅️", callback_data=f"stats:cal:years:{mode}:{prev_start}")
    kb.button(text="➡️", callback_data=f"stats:cal:years:{mode}:{next_start}")
    kb.button(text="🔙 К типу периода", callback_data="stats:calendar")

    kb.adjust(3, 3, 3, 2, 1)
    return kb.as_markup()


def _build_stats_months_kb(mode: str, year: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    month_labels = [
        "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
        "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
    ]
    for month in range(1, 13):
        kb.button(text=month_labels[month - 1], callback_data=f"stats:cal:month:{mode}:{year}:{month}")
    kb.button(text="🔙 К годам", callback_data=f"stats:cal:years:{mode}:{_normalize_stats_year_page_start(year - 4)}")
    kb.button(text="🔙 Назад", callback_data="stats:menu")
    kb.adjust(4, 4, 4, 2)
    return kb.as_markup()


def _build_stats_days_kb(year: int, month: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    days_in_month = calendar.monthrange(year, month)[1]
    for day in range(1, days_in_month + 1):
        kb.button(text=str(day), callback_data=f"stats:cal:day:{year}:{month}:{day}")

    kb.button(text="📦 Весь месяц", callback_data=f"stats:cal:month:month:{year}:{month}")
    kb.button(text="🔙 К месяцам", callback_data=f"stats:cal:year:day:{year}")
    kb.button(text="🔙 Назад", callback_data="stats:menu")
    kb.adjust(7, 7, 7, 7, 7, 7, 7, 3)
    return kb.as_markup()


def _stats_period_bounds(kind: str, year: int, month: int | None = None, day: int | None = None) -> tuple[datetime, datetime, str]:
    if kind == "day":
        if month is None or day is None:
            raise ValueError("month and day are required for day stats")
        start_date = datetime(year, month, day, 0, 0, 0)
        end_date = datetime(year, month, day, 23, 59, 59, 999999)
        period_name = f"день ({day:02d}.{month:02d}.{year})"
        return start_date, end_date, period_name

    if kind == "month":
        if month is None:
            raise ValueError("month is required for month stats")
        days_in_month = calendar.monthrange(year, month)[1]
        start_date = datetime(year, month, 1, 0, 0, 0)
        end_date = datetime(year, month, days_in_month, 23, 59, 59, 999999)
        period_name = f"месяц ({month:02d}.{year})"
        return start_date, end_date, period_name

    if kind == "year":
        start_date = datetime(year, 1, 1, 0, 0, 0)
        end_date = datetime(year, 12, 31, 23, 59, 59, 999999)
        period_name = f"год ({year})"
        return start_date, end_date, period_name

    raise ValueError(f"Unknown stats period kind: {kind}")


async def _show_stats_period_report(callback: CallbackQuery, repo: OrdersRepo, start_date: datetime, end_date: datetime, period_name: str) -> None:
    stats = await repo.get_stats_for_period(start_date, end_date)
    text = (
        f"📊 <b>Отчет за {period_name}:</b>\n\n"
        f"📦 Заказов: <b>{stats['count']}</b>\n"
        f"💰 Выручка: <b>{stats['revenue']:.2f} ₽</b>\n"
        f"💵 Маржинальная прибыль: <b>{stats['profit']:.2f} ₽</b>\n"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Календарь", callback_data="stats:calendar")
    kb.button(text="🔙 Назад", callback_data="stats:menu")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


async def _render_stats_menu(message: Message, edit: bool) -> None:
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 За сегодня", callback_data="stats:day")
    kb.button(text="📅 Календарь", callback_data="stats:calendar")
    kb.button(text="🌍 За всё время", callback_data="stats:all")
    kb.button(text="🏆 Топ товаров", callback_data="stats:top")
    kb.button(text="🔙 Назад", callback_data="owner:cancel")
    kb.adjust(1)

    if edit:
        await message.edit_text("📊 <b>Панель аналитики:</b>", reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        await message.answer("📊 <b>Панель аналитики:</b>", reply_markup=kb.as_markup(), parse_mode="HTML")


@main_router.message(F.text == "📈 Статистика")
@owner_only
async def owner_stats_menu(message: Message, session: AsyncSession) -> None:
    await _render_stats_menu(message, edit=False)


@main_router.callback_query(F.data.startswith("stats:"))
@owner_only
async def owner_stats_show(callback: CallbackQuery, session: AsyncSession) -> None:
    period = callback.data.split(":")[1]
    repo = OrdersRepo(session)
    now = datetime.utcnow()

    if period == "day":
        start_date = datetime(now.year, now.month, now.day)
        period_name = "сегодня"
        await _show_stats_period_report(callback, repo, start_date, now, period_name)
        return
    elif period == "calendar":
        await callback.message.edit_text(
            "📅 <b>Календарь статистики</b>\nВыберите тип периода:",
            reply_markup=_build_stats_calendar_mode_kb(),
            parse_mode="HTML",
        )
        return
    elif period == "cal":
        parts = callback.data.split(":")
        action = parts[2] if len(parts) > 2 else ""

        if action == "mode" and len(parts) == 4:
            mode = parts[3]
            if mode not in {"day", "month", "year"}:
                await callback.answer("Неизвестный тип периода", show_alert=True)
                return
            start_year = _normalize_stats_year_page_start(datetime.utcnow().year - 4)
            await callback.message.edit_text(
                f"📅 <b>Выберите год ({'день' if mode == 'day' else 'месяц' if mode == 'month' else 'год'})</b>",
                reply_markup=_build_stats_years_kb(mode, start_year),
                parse_mode="HTML",
            )
            return

        if action == "years" and len(parts) == 5:
            mode = parts[3]
            if mode not in {"day", "month", "year"}:
                await callback.answer("Неизвестный тип периода", show_alert=True)
                return
            start_year = _normalize_stats_year_page_start(int(parts[4]))
            await callback.message.edit_text(
                f"📅 <b>Выберите год ({'день' if mode == 'day' else 'месяц' if mode == 'month' else 'год'})</b>",
                reply_markup=_build_stats_years_kb(mode, start_year),
                parse_mode="HTML",
            )
            return

        if action == "year" and len(parts) == 5:
            mode = parts[3]
            year = int(parts[4])
            if mode == "year":
                start_date, end_date, period_name = _stats_period_bounds("year", year)
                await _show_stats_period_report(callback, repo, start_date, end_date, period_name)
                return
            if mode in {"day", "month"}:
                await callback.message.edit_text(
                    f"🗓 <b>Выберите месяц ({year})</b>",
                    reply_markup=_build_stats_months_kb(mode, year),
                    parse_mode="HTML",
                )
                return
            await callback.answer("Неизвестный тип периода", show_alert=True)
            return

        if action == "month" and len(parts) == 6:
            mode = parts[3]
            year = int(parts[4])
            month = int(parts[5])
            if mode == "month":
                start_date, end_date, period_name = _stats_period_bounds("month", year, month=month)
                await _show_stats_period_report(callback, repo, start_date, end_date, period_name)
                return
            if mode == "day":
                await callback.message.edit_text(
                    f"📅 <b>Выберите день ({month:02d}.{year})</b>",
                    reply_markup=_build_stats_days_kb(year, month),
                    parse_mode="HTML",
                )
                return
            await callback.answer("Неизвестный тип периода", show_alert=True)
            return

        if action == "day" and len(parts) == 6:
            year = int(parts[3])
            month = int(parts[4])
            day = int(parts[5])
            start_date, end_date, period_name = _stats_period_bounds("day", year, month=month, day=day)
            await _show_stats_period_report(callback, repo, start_date, end_date, period_name)
            return

        await callback.answer("Некорректный формат календаря", show_alert=True)
        return
    elif period == "all":
        start_date = datetime(2020, 1, 1)
        period_name = "всё время"
        await _show_stats_period_report(callback, repo, start_date, now, period_name)
        return
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
