from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from html import escape

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message,
    CallbackQuery,
    InputMediaPhoto,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.media_group import MediaGroupBuilder

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.catalog_repo import CatalogRepo
from database.orders_repo import OrdersRepo
from models import Category, Brand, Product, User, CartItem, UserRole, OrderStatus
from utils.error_policy import safe_delete_message, safe_edit_text
from utils.tenants import (
    get_membership_for_user,
    get_or_create_default_tenant_user,
    get_primary_owner_tg_id,
    get_runtime_tenant_role_for_tg_id,
    get_runtime_tenant,
    list_tenant_recipient_ids,
    list_tenant_user_ids_by_role,
)

client_router = Router()
logger = logging.getLogger(__name__)

CLIENT_CATEGORIES_PAGE_SIZE = 5
CLIENT_HISTORY_PAGE_SIZE = 4
CLIENT_ACTIVE_PAGE_SIZE = 4

# ---------- FSM (Машина состояний) ----------

class ClientStates(StatesGroup):
    # Состояние для добавления в корзину
    waiting_for_size = State()
    waiting_for_quantity = State()
    
    # Состояния для оформления заказа
    order_waiting_for_name = State()
    order_waiting_for_phone = State()

    # Общение с поддержкой
    chat_with_owner = State()
    chat_with_seller = State()
    chat_with_support = State()


def _client_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=settings.button_catalog), KeyboardButton(text=settings.button_cart)],
            [KeyboardButton(text=settings.button_orders), KeyboardButton(text=settings.button_ai)],
            [KeyboardButton(text=settings.button_support)],
        ],
        resize_keyboard=True,
    )


def _orders_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ История покупок")],
            [KeyboardButton(text="🚚 Заказы в пути")],
            [KeyboardButton(text="🏠 Меню")],
        ],
        resize_keyboard=True,
    )


def _is_back_text(text: str | None) -> bool:
    return text in {"⬅ Назад", "🔙 Назад", "↩️ Назад", "Отмена", "🏠 Меню"}


def _build_support_reply_kb(client_id: int, can_block: bool, is_blocked: bool) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Ответить", callback_data=f"contact:reply:{client_id}")
    if can_block:
        if is_blocked:
            kb.button(text="✅ Разблокировать", callback_data=f"contact:unblock:{client_id}")
        else:
            kb.button(text="⛔ Заблокировать", callback_data=f"contact:block:{client_id}")
    kb.adjust(1)
    return kb


# ---------- Клавиатуры ----------

def build_categories_kb(
    categories: list[Category],
    page: int,
    total_count: int,
    page_size: int,
) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    layout: list[int] = []
    for c in categories:
        kb.button(text=c.name, callback_data=f"cat:{page}:{c.id}")
        layout.append(1)

    total_pages = max(1, (total_count + page_size - 1) // page_size)
    if total_pages > 1:
        nav_count = 0
        if page > 1:
            kb.button(text="⬅️", callback_data=f"catpage:{page - 1}")
            nav_count += 1
        kb.button(text=f"{page}/{total_pages}", callback_data="catalog:noop")
        nav_count += 1
        if page < total_pages:
            kb.button(text="➡️", callback_data=f"catpage:{page + 1}")
            nav_count += 1
        layout.append(max(1, nav_count))

    kb.adjust(*layout)
    return kb

def build_brands_kb(
    category_id: int,
    brands: list[Brand],
    page: int,
    total_count: int,
    page_size: int,
    source_category_page: int,
) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for b in brands:
        kb.button(text=b.name, callback_data=f"brand:{category_id}:{b.id}")

    total_pages = (total_count + page_size - 1) // page_size
    nav_count = 0
    if page > 1:
        kb.button(text="⬅️", callback_data=f"brandpage:{source_category_page}:{category_id}:{page-1}")
        nav_count += 1
    kb.button(text=f"{page}/{total_pages}", callback_data="catalog:noop")
    nav_count += 1
    if page < total_pages:
        kb.button(text="➡️", callback_data=f"brandpage:{source_category_page}:{category_id}:{page+1}")
        nav_count += 1

    kb.button(text="⬅ Назад", callback_data=f"back:categories:{source_category_page}")

    layout = [1] * max(1, len(brands))
    layout.append(max(1, nav_count))
    layout.append(1)
    kb.adjust(*layout)
    return kb

def build_products_kb(
    category_id: int, 
    brand_id: int, 
    products: list[Product], 
    page: int, 
    total_count: int, 
    page_size: int
) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    
    # 1. Кнопки товаров
    for p in products:
        kb.button(text=p.title, callback_data=f"prod:{category_id}:{brand_id}:{p.id}")
    
    # 2. Кнопки навигации
    total_pages = (total_count + page_size - 1) // page_size

    nav_count = 0
    if page > 1:
        kb.button(text="⬅️", callback_data=f"page:{category_id}:{brand_id}:{page-1}")
        nav_count += 1

    kb.button(text=f"{page}/{total_pages}", callback_data="ignore")
    nav_count += 1

    if page < total_pages:
        kb.button(text="➡️", callback_data=f"page:{category_id}:{brand_id}:{page+1}")
        nav_count += 1

    # 3. Кнопка "Назад в бренды"
    kb.button(text="🔙 К брендам", callback_data=f"back:brands:{category_id}")

    layout = [1] * max(1, len(products))
    layout.append(max(1, nav_count))
    layout.append(1)
    kb.adjust(*layout)

    return kb

def build_cart_kb(items: list[CartItem]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    layout: list[int] = []
    if items:
        kb.button(text="✅ Оформить заказ", callback_data="order:start")
        layout.append(1)
    
    for it in items:
        kb.button(text="-1", callback_data=f"cart:qty:{it.id}:-1")
        kb.button(text=f"{it.quantity} шт.", callback_data="cart:noop")
        kb.button(text="+1", callback_data=f"cart:qty:{it.id}:1")
        layout.append(3)

        title = it.product.title if it.product else f"ID {it.product_id}"
        sku = it.product.sku if it.product else None
        title_with_sku = f"{title} [{sku}]" if sku else title
        kb.button(text=f"🗑 Удалить: {title_with_sku} ({it.size})", callback_data=f"cart:del:{it.id}")
        layout.append(1)
    
    kb.button(text="⬅ В каталог", callback_data="back:categories")
    layout.append(1)
    kb.adjust(*layout)
    return kb


def _build_client_history_kb(page: int, total_pages: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    nav_count = 0
    if total_pages > 1 and page > 1:
        kb.button(text="⬅️", callback_data=f"client:history:page:{page - 1}")
        nav_count += 1
    kb.button(text=f"{page}/{total_pages}", callback_data="client:history:noop")
    nav_count += 1
    if total_pages > 1 and page < total_pages:
        kb.button(text="➡️", callback_data=f"client:history:page:{page + 1}")
        nav_count += 1

    kb.button(text="🔙 К заказам", callback_data="client:history:menu")
    kb.adjust(max(1, nav_count), 1)
    return kb


def _build_client_active_orders_kb(page: int, total_pages: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    nav_count = 0
    if total_pages > 1 and page > 1:
        kb.button(text="⬅️", callback_data=f"client:active:page:{page - 1}")
        nav_count += 1
    kb.button(text=f"{page}/{total_pages}", callback_data="client:active:noop")
    nav_count += 1
    if total_pages > 1 and page < total_pages:
        kb.button(text="➡️", callback_data=f"client:active:page:{page + 1}")
        nav_count += 1

    kb.button(text="🔙 К заказам", callback_data="client:active:menu")
    kb.adjust(max(1, nav_count), 1)
    return kb


def _build_client_order_cancel_kb(order_id: int, confirming: bool = False) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    if confirming:
        kb.button(text="✅ Подтвердить отмену", callback_data=f"client:order:cancel_do:{order_id}")
        kb.button(text="↩️ Не отменять", callback_data=f"client:order:cancel_keep:{order_id}")
        kb.adjust(1)
    else:
        kb.button(text="🗑 Отменить заказ", callback_data=f"client:order:cancel_confirm:{order_id}")
        kb.adjust(1)
    return kb


async def _get_catalog_repo(session: AsyncSession) -> CatalogRepo:
    tenant = await get_runtime_tenant(session)
    return CatalogRepo(session, tenant_id=tenant.id)


async def _render_client_orders_history(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    page: int,
    edit: bool,
    requester_user_id: int | None = None,
) -> None:
    user_tg_id = requester_user_id if requester_user_id is not None else message.from_user.id

    stmt = select(User).where(User.tg_id == user_tg_id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user:
        if edit:
            await message.edit_text("Сначала нажмите /start")
        else:
            await message.answer("Сначала нажмите /start")
        return

    repo = OrdersRepo(session)
    orders = await repo.get_user_completed_orders(user.id)

    if not orders:
        if edit:
            await message.edit_text("📭 У вас пока нет завершенных покупок.")
        else:
            await message.answer("📭 У вас пока нет завершенных покупок.")
        await state.update_data(client_history_msg_ids=[])
        return

    total_count = len(orders)
    total_pages = max(1, (total_count + CLIENT_HISTORY_PAGE_SIZE - 1) // CLIENT_HISTORY_PAGE_SIZE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * CLIENT_HISTORY_PAGE_SIZE
    orders_slice = orders[offset:offset + CLIENT_HISTORY_PAGE_SIZE]

    data = await state.get_data()
    old_ids = data.get("client_history_msg_ids", [])
    current_msg_id = getattr(message, "message_id", None)
    if old_ids:
        for msg_id in old_ids:
            if current_msg_id and msg_id == current_msg_id:
                continue
            try:
                await message.bot.delete_message(chat_id=message.chat.id, message_id=msg_id)
            except Exception:
                continue
        await state.update_data(client_history_msg_ids=[])

    header_text = (
        f"📦 <b>История ваших покупок</b>\n"
        f"Страница {page}/{total_pages} | Всего заказов: {total_count}"
    )
    header_kb = _build_client_history_kb(page, total_pages)

    if edit:
        await message.edit_text(header_text, parse_mode="HTML", reply_markup=header_kb.as_markup())
    else:
        await message.answer(header_text, parse_mode="HTML", reply_markup=header_kb.as_markup())

    sent_ids: list[int] = []
    for order in orders_slice:
        items_lines = []
        for item in order.items:
            if item.product:
                brand = item.product.brand.name if item.product.brand else ""
                title = item.product.title
                sku = item.product.sku if item.product.sku else None
                sku_part = f" [{sku}]" if sku else ""
                name_str = f"{brand} {title}{sku_part}"
            else:
                name_str = "Товар удалён"

            price_fmt = f"{item.sale_price:g}"
            items_lines.append(f"— {name_str} ({item.size}) x{item.quantity} = {price_fmt} ₽")

        items_text = "\n".join(items_lines)
        date_str = order.created_at.strftime('%d.%m.%Y')
        total_fmt = f"{order.total_price:g}"

        msg_text = (
            f"✅ <b>Заказ #{order.id} от {date_str}</b>\n"
            f"{items_text}\n"
            f"💰 <b>Итого: {total_fmt} ₽</b>"
        )

        sent = await message.answer(msg_text, parse_mode="HTML")
        sent_ids.append(sent.message_id)
        await asyncio.sleep(0.05)

    await state.update_data(client_history_msg_ids=sent_ids, client_history_page=page)


# ---------- Команды (Меню) ----------

@client_router.message(Command("catalog"))
async def cmd_catalog(message: Message, session: AsyncSession) -> None:
    await show_categories_page(message, session, page=1)


async def show_categories_page(message: Message, session: AsyncSession, page: int) -> None:
    repo = await _get_catalog_repo(session)
    total_count = await repo.count_categories()

    if total_count == 0:
        await message.answer("Категории пока не созданы.")
        return

    total_pages = max(1, (total_count + CLIENT_CATEGORIES_PAGE_SIZE - 1) // CLIENT_CATEGORIES_PAGE_SIZE)
    page = max(1, min(page, total_pages))
    categories = await repo.list_categories_paginated(page, CLIENT_CATEGORIES_PAGE_SIZE)
    kb = build_categories_kb(list(categories), page, total_count, CLIENT_CATEGORIES_PAGE_SIZE)
    await message.answer("Выбери категорию:", reply_markup=kb.as_markup())


async def show_categories_page_from_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    page: int,
) -> None:
    repo = await _get_catalog_repo(session)
    total_count = await repo.count_categories()

    if total_count == 0:
        await callback.message.answer("Категории пока не созданы.")
        await callback.answer()
        return

    total_pages = max(1, (total_count + CLIENT_CATEGORIES_PAGE_SIZE - 1) // CLIENT_CATEGORIES_PAGE_SIZE)
    page = max(1, min(page, total_pages))
    categories = await repo.list_categories_paginated(page, CLIENT_CATEGORIES_PAGE_SIZE)
    kb = build_categories_kb(list(categories), page, total_count, CLIENT_CATEGORIES_PAGE_SIZE)

    try:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer("Выбери категорию:", reply_markup=kb.as_markup())
        else:
            await callback.message.edit_text("Выбери категорию:", reply_markup=kb.as_markup())
    finally:
        await callback.answer()


# ---------- Общение с продавцом/владельцем ----------

@client_router.message(F.text == "💬 Продавец")
async def start_chat_with_seller(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(ClientStates.chat_with_seller)
    await message.answer(
        "✉️ Напишите сообщение продавцу. Для выхода нажмите «🔙 Назад».",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Назад")]],
            resize_keyboard=True,
        ),
    )


@client_router.message(F.text == "💬 Владелец")
async def start_chat_with_owner(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(ClientStates.chat_with_owner)
    await message.answer(
        "✉️ Напишите сообщение владельцу. Для выхода нажмите «🔙 Назад».",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Назад")]],
            resize_keyboard=True,
        ),
    )


@client_router.message(F.text == settings.button_support)
async def open_support_menu(message: Message, state: FSMContext) -> None:
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✍️ Написать")],
            [KeyboardButton(text="🏠 Меню")],
        ],
        resize_keyboard=True,
    )
    await message.answer("Выберите действие:", reply_markup=kb)


@client_router.message(F.text == "✍️ Написать")
async def start_chat_with_support(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(ClientStates.chat_with_support)
    await message.answer(
        "✉️ Напишите сообщение. Поддержка скоро ответит. Для выхода нажмите «🔙 Назад».",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Назад")]],
            resize_keyboard=True,
        ),
    )


@client_router.message(F.text == "🏠 Меню")
async def back_to_client_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Возвращаюсь в меню.", reply_markup=_client_menu_kb())


@client_router.message(ClientStates.chat_with_seller)
async def process_chat_with_seller(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if _is_back_text(message.text):
        await state.clear()
        await message.answer("Возвращаюсь в меню.", reply_markup=_client_menu_kb())
        return

    stmt = select(User).where(User.tg_id == message.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if user is None:
        user, _ = await get_or_create_default_tenant_user(
            session,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            default_role=UserRole.CLIENT.value,
            ai_quota=settings.ai_client_start_quota,
        )
        await session.commit()

    staff_ids = await list_tenant_user_ids_by_role(session, user.tenant_id or 0, UserRole.STAFF.value)
    if not staff_ids:
        await message.answer("⚠️ Сейчас нет продавцов на связи.")
        return

    username_line = f"@{user.username}" if user.username else "—"
    client_text = message.text or message.caption or "[медиа]"
    info_text = (
        f"💬 Сообщение от клиента:\n"
        f"👤 {user.full_name}\n"
        f"🆔 {user.tg_id}\n"
        f"{username_line}\n\n"
        f"Сообщение:\n{client_text}"
    )

    delivered = 0
    kb = _build_support_reply_kb(user.tg_id, can_block=False, is_blocked=False)
    for staff_id in staff_ids:
        try:
            await message.bot.send_message(
                chat_id=staff_id,
                text=info_text,
                reply_markup=kb.as_markup(),
            )
            if not message.text:
                await message.bot.copy_message(
                    chat_id=staff_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )
            delivered += 1
        except Exception:
            continue

    if staff_ids and delivered == 0:
        owner_tg_id = await get_primary_owner_tg_id(session, user.tenant_id or 0)
        if owner_tg_id:
            await message.bot.send_message(
                chat_id=owner_tg_id,
                text="⚠️ Сообщение клиента не доставлено ни одному сотруднику. Проверьте, что они нажали /start и не заблокировали бота.",
            )

    await message.answer("✅ Сообщение отправлено продавцу.")


@client_router.message(ClientStates.chat_with_owner)
async def process_chat_with_owner(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if _is_back_text(message.text):
        await state.clear()
        await message.answer("Возвращаюсь в меню.", reply_markup=_client_menu_kb())
        return

    stmt = select(User).where(User.tg_id == message.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if user is None:
        user, _ = await get_or_create_default_tenant_user(
            session,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            default_role=UserRole.CLIENT.value,
            ai_quota=settings.ai_client_start_quota,
        )
        await session.commit()

    username_line = f"@{user.username}" if user.username else "—"
    info_text = (
        f"💬 Сообщение от клиента:\n"
        f"👤 {user.full_name}\n"
        f"🆔 {user.tg_id}\n"
        f"{username_line}"
    )

    owner_tg_id = await get_primary_owner_tg_id(session, user.tenant_id or 0)
    if not owner_tg_id:
        await message.answer("⚠️ В tenant не назначен владелец.")
        return

    membership = await get_membership_for_user(session, user, user.tenant_id or 0)
    kb = _build_support_reply_kb(user.tg_id, can_block=True, is_blocked=bool(membership and membership.is_blocked))
    try:
        await message.bot.forward_message(
            chat_id=owner_tg_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        await message.bot.send_message(
            chat_id=owner_tg_id,
            text=info_text,
            reply_markup=kb.as_markup(),
        )
    except Exception:
        await message.answer("⚠️ Не удалось отправить сообщение владельцу.")
        return

    await message.answer("✅ Сообщение отправлено владельцу.")


@client_router.message(ClientStates.chat_with_support)
async def process_chat_with_support(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if _is_back_text(message.text):
        await state.clear()
        await message.answer("Возвращаюсь в меню.", reply_markup=_client_menu_kb())
        return

    stmt = select(User).where(User.tg_id == message.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if user is None:
        user, _ = await get_or_create_default_tenant_user(
            session,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            default_role=UserRole.CLIENT.value,
            ai_quota=settings.ai_client_start_quota,
        )
        await session.commit()

    username_line = f"@{user.username}" if user.username else "—"
    info_text = (
        f"💬 Сообщение от клиента:\n"
        f"👤 {user.full_name}\n"
        f"🆔 {user.tg_id}\n"
        f"{username_line}"
    )

    owner_tg_id = await get_primary_owner_tg_id(session, user.tenant_id or 0)
    staff_ids = [
        sid
        for sid in await list_tenant_user_ids_by_role(session, user.tenant_id or 0, UserRole.STAFF.value)
        if sid and sid != owner_tg_id
    ]

    membership = await get_membership_for_user(session, user, user.tenant_id or 0)
    kb_owner = _build_support_reply_kb(user.tg_id, can_block=True, is_blocked=bool(membership and membership.is_blocked))
    kb_staff = _build_support_reply_kb(user.tg_id, can_block=False, is_blocked=False)

    staff_delivered = 0
    targets = [target_id for target_id in [owner_tg_id, *staff_ids] if target_id]
    for target_id in targets:
        try:
            await message.bot.send_message(
                chat_id=target_id,
                text=info_text,
                reply_markup=(kb_owner if target_id == owner_tg_id else kb_staff).as_markup(),
            )
            await message.bot.copy_message(
                chat_id=target_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            if target_id != owner_tg_id:
                staff_delivered += 1
        except Exception:
            continue

    if owner_tg_id and staff_ids and staff_delivered == 0:
        await message.bot.send_message(
            chat_id=owner_tg_id,
            text="⚠️ Сообщение клиента не доставлено ни одному сотруднику. Проверьте, что они нажали /start и не заблокировали бота.",
        )

    await message.answer("✅ Поддержка скоро ответит.")

async def show_cart_for(
    user_id: int,
    username: str | None,
    first_name: str | None,
    message: Message,
    session: AsyncSession,
) -> None:
    stmt = select(User).where(User.tg_id == user_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    if user is None:
        user, _ = await get_or_create_default_tenant_user(
            session,
            tg_id=user_id,
            username=username,
            first_name=first_name,
            last_name=None,
            default_role=UserRole.CLIENT.value,
            ai_quota=0,
        )
        await session.commit()

    orders_repo = OrdersRepo(session, tenant_id=user.tenant_id)
    items = await orders_repo.list_cart_items(user)
    total = await orders_repo.get_cart_total(user)

    if not items:
        await message.answer("Корзина пуста.")
        return

    lines = ["🛒 <b>Твоя корзина:</b>"]

    for it in items:
        if it.product and it.product.brand:
            brand_name = it.product.brand.name
        else:
            brand_name = "Бренд не указан"

        product_title = it.product.title if it.product else "Товар удалён"
        product_sku = it.product.sku if (it.product and it.product.sku) else None

        sku_line = f"   SKU: {product_sku}\n" if product_sku else ""
        line_total = float(it.price_at_add) * int(it.quantity)
        lines.append(
            f"▫️ <b>{brand_name}</b> | {product_title}\n"
            f"{sku_line}"
            f"   Размер: {it.size} | {it.quantity} шт. x {it.price_at_add} ₽ = {line_total:,.0f} ₽"
        )

    lines.append(f"\n💰 <b>Итого: {total} ₽</b>")
    lines.append("\nИзменяйте количество кнопками -1 и +1 под каждой позицией.")

    kb = build_cart_kb(list(items))
    await message.answer("\n".join(lines), reply_markup=kb.as_markup(), parse_mode="HTML")


@client_router.message(Command("cart"))
async def cmd_cart(message: Message, session: AsyncSession) -> None:
    await show_cart_for(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        message=message,
        session=session,
    )


# ---------- Навигация по Каталогу ----------

@client_router.callback_query(F.data.startswith("cat:"))
async def cq_category(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    if len(parts) == 3:
        source_category_page = int(parts[1])
        category_id = int(parts[2])
    else:
        source_category_page = 1
        category_id = int(parts[1])

    repo = await _get_catalog_repo(session)
    cat = await repo.get_category(category_id)
    if not cat:
        await callback.answer("Категория не найдена")
        return

    total_count = await repo.count_brands_by_category(category_id)
    if total_count == 0:
        try:
            if callback.message.photo:
                await callback.message.delete()
                await callback.message.answer(
                    f"В категории <b>{cat.name}</b> пока нет товаров (и брендов).",
                    parse_mode="HTML"
                )
            else:
                await callback.message.edit_text(
                    f"В категории <b>{cat.name}</b> пока нет товаров (и брендов).",
                    parse_mode="HTML"
                )
        finally:
            await callback.answer()
        return

    await show_brands_page(callback, session, category_id, page=1, source_category_page=source_category_page)
    return

@client_router.callback_query(F.data.startswith("catpage:"))
async def cq_categories_page(callback: CallbackQuery, session: AsyncSession) -> None:
    page = int(callback.data.split(":")[1])
    await show_categories_page_from_callback(callback, session, page)

@client_router.callback_query(F.data.startswith("brandpage:"))
async def cq_brand_page(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    if len(parts) == 4:
        source_category_page = int(parts[1])
        category_id = int(parts[2])
        page = int(parts[3])
    else:
        source_category_page = 1
        category_id = int(parts[1])
        page = int(parts[2])
    await show_brands_page(callback, session, category_id, page, source_category_page=source_category_page)

async def show_brands_page(
    callback: CallbackQuery,
    session: AsyncSession,
    category_id: int,
    page: int,
    source_category_page: int = 1,
) -> None:
    PAGE_SIZE = 8
    repo = await _get_catalog_repo(session)
    cat = await repo.get_category(category_id)
    total_count = await repo.count_brands_by_category(category_id)

    if not cat or total_count == 0:
        await callback.answer("Категории пока нет брендов", show_alert=True)
        return

    brands = await repo.get_brands_by_category_paginated(category_id, page, PAGE_SIZE)
    kb = build_brands_kb(category_id, list(brands), page, total_count, PAGE_SIZE, source_category_page)
    text = f"📂 Категория: <b>{cat.name}</b>\nВыберите бренд:"

    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            text,
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            text,
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
    
    await callback.answer()

@client_router.callback_query(F.data.startswith("brand:"))
async def cq_brand(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    category_id = int(parts[1])
    brand_id = int(parts[2])
    
    await show_products_page(callback, session, category_id, brand_id, page=1)

async def show_products_page(callback: CallbackQuery, session: AsyncSession, cat_id: int, brand_id: int, page: int):
    PAGE_SIZE = 5
    
    repo = await _get_catalog_repo(session)
    
    products = await repo.get_products_by_category_brand_paginated(cat_id, brand_id, page, PAGE_SIZE)
    total_count = await repo.count_products_by_category_brand(cat_id, brand_id)
    
    brand = await repo.get_brand(brand_id)
    brand_name = brand.name if brand else "Бренд"

    if not products and page == 1:
        await callback.message.edit_text(f"В бренде {brand_name} пока нет товаров.")
        return

    kb = build_products_kb(cat_id, brand_id, list(products), page, total_count, PAGE_SIZE)
    
    text = f"🏷 Бренд: <b>{brand_name}</b>\nВыберите модель:"

    if callback.message.photo:
        await safe_delete_message(callback.message, logger, "show_products_page.photo")
        await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        await safe_edit_text(
            callback.message,
            logger,
            "show_products_page.text",
            text,
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
            
    await callback.answer()


@client_router.callback_query(F.data.startswith("page:"))
async def cq_page(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    category_id = int(parts[1])
    brand_id = int(parts[2])
    page = int(parts[3])

    await show_products_page(callback, session, category_id, brand_id, page)


@client_router.callback_query(F.data.startswith("prod:"))
async def cq_product(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    try:
        parts = callback.data.split(":")
        category_id = int(parts[1])
        brand_id = int(parts[2])
        product_id = int(parts[3])

        repo = await _get_catalog_repo(session)
        product = await repo.get_product_with_details(product_id)
    except (IndexError, ValueError) as exc:
        logger.warning("Invalid product callback payload: %s (%s)", callback.data, exc)
        await callback.answer("Некорректный формат запроса.", show_alert=True)
        return
    except Exception as exc:
        logger.exception("Failed to resolve product card callback=%s: %s", callback.data, exc)
        await callback.answer("Ошибка обработки запроса. Проверьте логи.", show_alert=True)
        return

    if not product:
        await callback.answer("Товар не найден.", show_alert=True)
        return

    stmt = select(User).where(User.tg_id == callback.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    role = await get_runtime_tenant_role_for_tg_id(session, callback.from_user.id)
    is_staff = role in {UserRole.STAFF.value, UserRole.OWNER.value}

    available_sizes = [f"{s.size}" for s in product.stock if s.quantity > 0]
    sizes_str = ", ".join(available_sizes) if available_sizes else "Нет в наличии"
    stock_details = ", ".join(
        [f"{s.size} ({s.quantity})" for s in product.stock if s.quantity > 0]
    )

    brand_name = product.brand.name if product.brand else "Бренд не указан"
    text = (
        f"🏷 {product.title}\n"
        f"🏷️ Бренд: {brand_name}\n"
        f"🔖 SKU: {product.sku}\n"
        f"🆔 ID: {product.id}\n\n"
        f"💰 Цена: {product.sale_price} ₽\n"
        f"📏 Размеры в наличии: {sizes_str}\n"
    )
    if is_staff and stock_details:
        text += f"📦 Остатки: {stock_details}\n"
    if product.description:
        text += f"\nℹ️ {product.description}"

    kb = InlineKeyboardBuilder()
    if is_staff:
        await state.update_data(product_id=product_id)
        kb.button(text="📝 Изм. Описание", callback_data="edit:action:desc")
        kb.button(text="🖼 Добавить фото", callback_data="edit:action:photo")
    else:
        if available_sizes:
            kb.button(text="🛒 В корзину", callback_data=f"cart:add:{product_id}")
        else:
            kb.button(text="🚫 Нет в наличии", callback_data="ignore")
    
    if category_id == 0 and brand_id == 0:
        kb.button(text="↩️ Закрыть", callback_data="ignore")
    else:
        kb.button(text="⬅ Назад", callback_data=f"back:products:{category_id}:{brand_id}")
    kb.adjust(1)

    await safe_delete_message(callback.message, logger, "cq_product.card")

    if product.photos:
        if len(product.photos) > 1:
            from utils.product_media import build_product_media_group

            album = build_product_media_group(product.photos, text)
            await callback.message.answer_media_group(media=album.build())
            await callback.message.answer("👇 Действия:", reply_markup=kb.as_markup())
            
        else:
            from utils.product_media import normalize_media_type

            media = product.photos[0]
            if normalize_media_type(getattr(media, "media_type", None)) == "video":
                await callback.message.answer_video(
                    video=media.file_id,
                    caption=text,
                    reply_markup=kb.as_markup()
                )
            else:
                await callback.message.answer_photo(
                    photo=media.file_id,
                    caption=text,
                    reply_markup=kb.as_markup()
                )
    else:
        await callback.message.answer(text, reply_markup=kb.as_markup())
    
    await callback.answer()


# ---------- Кнопки "Назад" ----------

@client_router.callback_query(F.data == "back:categories")
async def cq_back_categories(callback: CallbackQuery, session: AsyncSession) -> None:
    await show_categories_page_from_callback(callback, session, page=1)


@client_router.callback_query(F.data.startswith("back:categories:"))
async def cq_back_categories_page(callback: CallbackQuery, session: AsyncSession) -> None:
    page = int(callback.data.split(":")[2])
    await show_categories_page_from_callback(callback, session, page=page)

@client_router.callback_query(F.data == "catalog_start")
async def cq_catalog_start(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await cmd_catalog(callback.message, session)
    finally:
        await callback.answer()

@client_router.callback_query(F.data.in_({"ignore", "catalog:noop"}))
async def cq_ignore(callback: CallbackQuery) -> None:
    await callback.answer()

@client_router.callback_query(F.data.startswith("back:brands:"))
async def cq_back_brands(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    category_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 1
    await show_brands_page(callback, session, category_id, page)

@client_router.callback_query(F.data.startswith("back:products:"))
async def cq_back_products(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    category_id = int(parts[2])
    brand_id = int(parts[3])
    await show_products_page(callback, session, category_id, brand_id, page=1)


# ---------- Добавление в корзину ----------

@client_router.callback_query(F.data.startswith("cart:add:"))
async def cq_cart_add(callback: CallbackQuery, state: FSMContext) -> None:
    product_id = int(callback.data.split(":")[2])
    await state.update_data(product_id=product_id)
    await state.set_state(ClientStates.waiting_for_size)
    await callback.message.answer("⌨️ Введите нужный размер (текстом):")
    await callback.answer()

@client_router.message(ClientStates.waiting_for_size)
async def process_size_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    size = message.text.strip()
    if _is_back_text(size):
        await state.clear()
        await message.answer("Добавление в корзину отменено.")
        return

    data = await state.get_data()
    product_id = data.get("product_id")

    repo = await _get_catalog_repo(session)
    product = await repo.get_product_with_details(product_id)

    if not product:
        await message.answer("Товар не найден. Откройте карточку заново.")
        await state.clear()
        return

    available_stock = [stock for stock in product.stock if stock.quantity > 0]
    match = next((stock for stock in available_stock if stock.size.lower() == size.lower()), None)
    if not match:
        sizes_str = ", ".join([stock.size for stock in available_stock]) or "нет"
        await message.answer(f"Такого размера нет. Доступно: {sizes_str}.")
        return

    await state.update_data(selected_size=match.size)
    await state.set_state(ClientStates.waiting_for_quantity)
    await message.answer(f"📦 Введите количество для размера {match.size} (доступно: {match.quantity}):")


@client_router.message(ClientStates.waiting_for_quantity)
async def process_quantity_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    quantity_text = (message.text or "").strip()
    if _is_back_text(quantity_text):
        await state.clear()
        await message.answer("Добавление в корзину отменено.")
        return

    try:
        quantity = int(quantity_text)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите количество целым числом больше нуля.")
        return

    stmt = select(User).where(User.tg_id == message.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    if user is None:
        user, _ = await get_or_create_default_tenant_user(
            session,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            default_role=UserRole.CLIENT.value,
            ai_quota=settings.ai_client_start_quota,
        )
        await session.commit()

    data = await state.get_data()
    product_id = data.get("product_id")
    size = data.get("selected_size")
    repo = await _get_catalog_repo(session)
    product = await repo.get_product_with_details(product_id)

    if not product or not size:
        await message.answer("Ошибка добавления. Откройте карточку товара заново.")
        await state.clear()
        return

    match = next((stock for stock in product.stock if stock.size == size and stock.quantity > 0), None)
    if not match:
        await message.answer("Этот размер уже закончился. Проверьте карточку товара ещё раз.")
        await state.clear()
        return

    orders_repo = OrdersRepo(session, tenant_id=user.tenant_id)
    cart_items = await orders_repo.list_cart_items(user)
    existing_qty = next(
        (
            item.quantity
            for item in cart_items
            if item.product_id == product.id and item.size.lower() == size.lower()
        ),
        0,
    )
    if existing_qty + quantity > match.quantity:
        available_to_add = match.quantity - existing_qty
        if available_to_add <= 0:
            await message.answer(f"В корзине уже максимум для размера {size}: {existing_qty} шт.")
        else:
            await message.answer(
                f"Нельзя добавить {quantity} шт. Для размера {size} доступно только {available_to_add} шт с учетом корзины."
            )
        return

    await orders_repo.add_to_cart(user, product, size, quantity)
    await session.commit()

    await message.answer(
        f"✅ Товар <b>{product.title}</b> (размер {size}, количество {quantity}) добавлен в корзину!",
        parse_mode="HTML"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Перейти в корзину", callback_data="show:cart")
    kb.button(text="🛍 Продолжить покупки", callback_data="back:categories")
    await message.answer("Что дальше?", reply_markup=kb.as_markup())

    await state.clear()


# ---------- Управление корзиной ----------

async def _show_cart_from_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        await callback.message.delete()
    except Exception:
        pass
    await show_cart_for(
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
        message=callback.message,
        session=session,
    )

@client_router.callback_query(F.data == "show:cart")
async def cq_show_cart_cb(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        await _show_cart_from_callback(callback, session)
    finally:
        await callback.answer()

@client_router.callback_query(F.data == "cart:noop")
async def cq_cart_noop(callback: CallbackQuery) -> None:
    await callback.answer()

@client_router.callback_query(F.data.startswith("cart:qty:"))
async def cq_cart_change_qty(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, item_id_text, delta_text = callback.data.split(":")
    item_id = int(item_id_text)
    delta = int(delta_text)

    stmt = select(User).where(User.tg_id == callback.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if user is None:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    orders_repo = OrdersRepo(session, tenant_id=user.tenant_id)
    status, item, available_quantity = await orders_repo.change_cart_item_quantity(user, item_id, delta)

    if status == "not_found":
        await callback.answer("Позиция не найдена", show_alert=True)
        return

    if status == "min_reached":
        await callback.answer("Минимум для позиции: 1 шт. Для удаления используйте кнопку удаления.")
        return

    if status == "stock_limit":
        if available_quantity is None:
            await callback.answer("Товар закончился", show_alert=True)
        else:
            await callback.answer(f"Больше добавить нельзя: доступно только {available_quantity} шт.")
        return

    await session.commit()
    await _show_cart_from_callback(callback, session)
    updated_quantity = int(item.quantity) if item is not None else None
    if updated_quantity is None:
        await callback.answer("Количество обновлено")
    else:
        await callback.answer(f"Количество: {updated_quantity} шт.")

@client_router.callback_query(F.data.startswith("cart:del:"))
async def cq_cart_del(callback: CallbackQuery, session: AsyncSession) -> None:
    item_id = int(callback.data.split(":")[2])
    
    stmt = select(User).where(User.tg_id == callback.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    orders_repo = OrdersRepo(session, tenant_id=user.tenant_id if user else None)
    await orders_repo.delete_cart_item(user, item_id)
    await session.commit()

    await _show_cart_from_callback(callback, session)
    await callback.answer("Удалено")


# ---------- ОФОРМЛЕНИЕ ЗАКАЗА (Checkout) ----------

@client_router.callback_query(F.data == "order:start")
async def start_checkout(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ClientStates.order_waiting_for_name)
    await callback.message.answer("📝 Как к вам обращаться? (Введите имя)")
    await callback.answer()

@client_router.message(ClientStates.order_waiting_for_name)
async def process_order_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    await state.update_data(full_name=name)
    
    await state.set_state(ClientStates.order_waiting_for_phone)
    await message.answer("📱 Введите контактный телефон:")

@client_router.message(ClientStates.order_waiting_for_phone)
async def process_order_phone(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    phone = message.text.strip()
    data = await state.get_data()
    full_name = data.get("full_name")

    stmt = select(User).where(User.tg_id == message.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    orders_repo = OrdersRepo(session)
    cart_items = await orders_repo.list_cart_items(user)

    if not cart_items:
        await message.answer("Корзина пуста. Ошибка создания заказа.")
        await state.clear()
        return

    order = await orders_repo.create_order(
        user=user,
        full_name=full_name,
        phone=phone,
        address="Не указан (уточнить по телефону)", 
        cart_items=cart_items
    )

    if order is None:
        await message.answer(
            "⚠️ <b>Ошибка оформления!</b>\n\n"
            "К сожалению, пока вы оформляли заказ, один из товаров закончился на складе.\n"
            "Пожалуйста, проверьте корзину.",
            parse_mode="HTML"
        )
        await state.clear()
        return

    user.ai_quota += settings.ai_client_bonus_quota
    user.ai_bonus_at = datetime.utcnow()
    await orders_repo.clear_cart(user)
    await session.commit()

    await message.answer(
        f"✅ <b>Заказ #{order.id} оформлен!</b>\n"
        f"Менеджер свяжется с вами.\n"
        f"🎁 Начислено {settings.ai_client_bonus_quota} AI-запросов.",
        parse_mode="HTML",
    )
    
    items_list_text = ""
    for it in cart_items:
        brand = it.product.brand.name if (it.product and it.product.brand) else ""
        title = it.product.title if it.product else "???"
        sku = it.product.sku if (it.product and it.product.sku) else None
        sku_part = f" [{sku}]" if sku else ""
        items_list_text += f"— {brand} {title}{sku_part} ({it.size}) x{it.quantity}\n"

    try:
        safe_username = escape(message.from_user.username or "") if message.from_user.username else "—"
        admin_text = (
            f"🔔 <b>НОВЫЙ ЗАКАЗ #{order.id}</b>\n"
            f"👤 Клиент: {escape(full_name or '')} (@{safe_username})\n"
            f"📱 Телефон: {escape(phone or '')}\n"
            f"💰 Сумма: {order.total_price} ₽\n\n"
            f"📦 <b>Состав заказа:</b>\n"
            f"{items_list_text}"
        )
        owner_tg_id = await get_primary_owner_tg_id(session, user.tenant_id or order.tenant_id or 0)
        recipients = await list_tenant_recipient_ids(session, user.tenant_id or order.tenant_id or 0)
        for staff_id in recipients:
            if staff_id in {owner_tg_id, message.from_user.id}:
                continue
            try:
                await bot.send_message(staff_id, admin_text, parse_mode="HTML")
            except Exception as exc:
                logger.warning("Failed to send order notification to staff %s: %s", staff_id, exc)
                continue
        if owner_tg_id:
            await bot.send_message(owner_tg_id, admin_text, parse_mode="HTML")
    except Exception as exc:
        logger.error("Failed to send order notification to owner: %s", exc)

    await state.clear()

@client_router.message(F.text == settings.button_orders)
async def cmd_orders_menu(message: Message, session: AsyncSession) -> None:
    await message.answer("Выберите раздел заказов:", reply_markup=_orders_menu_kb())


@client_router.message(F.text == "✅ История покупок")
async def cmd_my_orders_history(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _render_client_orders_history(message, state, session, page=1, edit=False, requester_user_id=message.from_user.id)


@client_router.callback_query(F.data.startswith("client:history:"))
async def client_orders_history_cb(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    action = parts[2] if len(parts) > 2 else ""

    if action == "page" and len(parts) == 4 and parts[3].isdigit():
        page = int(parts[3])
        await _render_client_orders_history(callback.message, state, session, page=page, edit=True, requester_user_id=callback.from_user.id)
        await callback.answer()
        return

    if action == "noop":
        await callback.answer()
        return

    if action == "menu":
        await safe_delete_message(callback.message, logger, "client_orders_history.menu")
        await callback.message.answer("Выберите раздел заказов:", reply_markup=_orders_menu_kb())
        await callback.answer()
        return

    await callback.answer()


async def _render_client_active_orders(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    page: int,
    edit: bool,
    requester_user_id: int | None = None,
) -> None:
    user_tg_id = requester_user_id if requester_user_id is not None else message.from_user.id

    stmt = select(User).where(User.tg_id == user_tg_id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user:
        if edit:
            await message.edit_text("Сначала нажмите /start")
        else:
            await message.answer("Сначала нажмите /start")
        return

    repo = OrdersRepo(session)
    orders = await repo.get_user_active_orders(user.id)
    if not orders:
        if edit:
            await message.edit_text("🚚 У вас нет заказов в пути.")
        else:
            await message.answer("🚚 У вас нет заказов в пути.")
        await state.update_data(client_active_msg_ids=[])
        return

    total_count = len(orders)
    total_pages = max(1, (total_count + CLIENT_ACTIVE_PAGE_SIZE - 1) // CLIENT_ACTIVE_PAGE_SIZE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * CLIENT_ACTIVE_PAGE_SIZE
    orders_slice = orders[offset:offset + CLIENT_ACTIVE_PAGE_SIZE]

    data = await state.get_data()
    old_ids = data.get("client_active_msg_ids", [])
    current_msg_id = getattr(message, "message_id", None)
    if old_ids:
        for msg_id in old_ids:
            if current_msg_id and msg_id == current_msg_id:
                continue
            try:
                await message.bot.delete_message(chat_id=message.chat.id, message_id=msg_id)
            except Exception:
                continue
        await state.update_data(client_active_msg_ids=[])

    header_text = (
        f"🚚 <b>Заказы в пути</b>\n"
        f"Страница {page}/{total_pages} | Всего заказов: {total_count}"
    )
    header_kb = _build_client_active_orders_kb(page, total_pages)

    if edit:
        await message.edit_text(header_text, parse_mode="HTML", reply_markup=header_kb.as_markup())
    else:
        await message.answer(header_text, parse_mode="HTML", reply_markup=header_kb.as_markup())

    status_labels = {
        OrderStatus.NEW.value: "Новый",
        OrderStatus.PROCESSING.value: "В обработке",
    }

    sent_ids: list[int] = []
    for order in orders_slice:
        items_lines = []
        for item in order.items:
            if item.product:
                brand = item.product.brand.name if item.product.brand else ""
                title = item.product.title
                sku = item.product.sku if item.product.sku else None
                sku_part = f" [{sku}]" if sku else ""
                name_str = f"{brand} {title}{sku_part}"
            else:
                name_str = "Товар удалён"

            price_fmt = f"{item.sale_price:g}"
            items_lines.append(f"— {name_str} ({item.size}) x{item.quantity} = {price_fmt} ₽")

        items_text = "\n".join(items_lines)
        date_str = order.created_at.strftime('%d.%m.%Y')
        total_fmt = f"{order.total_price:g}"
        status_text = status_labels.get(order.status, order.status)

        msg_text = (
            f"🧾 <b>Заказ #{order.id} от {date_str}</b>\n"
            f"Статус: <b>{status_text}</b>\n"
            f"{items_text}\n"
            f"💰 <b>Итого: {total_fmt} ₽</b>"
        )

        sent = await message.answer(
            msg_text,
            parse_mode="HTML",
            reply_markup=_build_client_order_cancel_kb(order.id).as_markup(),
        )
        sent_ids.append(sent.message_id)
        await asyncio.sleep(0.05)

    await state.update_data(client_active_msg_ids=sent_ids, client_active_page=page)


@client_router.message(F.text == "🚚 Заказы в пути")
async def cmd_active_orders(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _render_client_active_orders(message, state, session, page=1, edit=False, requester_user_id=message.from_user.id)


@client_router.callback_query(F.data.startswith("client:active:"))
async def client_active_orders_cb(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    action = parts[2] if len(parts) > 2 else ""

    if action == "page" and len(parts) == 4 and parts[3].isdigit():
        page = int(parts[3])
        await _render_client_active_orders(callback.message, state, session, page=page, edit=True, requester_user_id=callback.from_user.id)
        await callback.answer()
        return

    if action == "noop":
        await callback.answer()
        return

    if action == "menu":
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer("Выберите раздел заказов:", reply_markup=_orders_menu_kb())
        await callback.answer()
        return

    await callback.answer()


@client_router.callback_query(F.data.startswith("client:order:cancel_confirm:"))
async def client_cancel_order_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    order_id = int(callback.data.split(":")[-1])

    stmt = select(User).where(User.tg_id == callback.from_user.id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    repo = OrdersRepo(session)
    active_orders = await repo.get_user_active_orders(user.id)
    target_order = next((order for order in active_orders if order.id == order_id), None)
    if not target_order:
        await callback.answer("Заказ уже недоступен для отмены", show_alert=True)
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=_build_client_order_cancel_kb(order_id, confirming=True).as_markup())
    except Exception:
        pass
    await callback.answer("Подтвердите отмену")


@client_router.callback_query(F.data.startswith("client:order:cancel_keep:"))
async def client_cancel_order_keep(callback: CallbackQuery) -> None:
    order_id = int(callback.data.split(":")[-1])
    try:
        await callback.message.edit_reply_markup(reply_markup=_build_client_order_cancel_kb(order_id, confirming=False).as_markup())
    except Exception:
        pass
    await callback.answer("Отмена не выполнена")


@client_router.callback_query(F.data.startswith("client:order:cancel_do:"))
async def client_cancel_active_order(callback: CallbackQuery, session: AsyncSession) -> None:
    order_id = int(callback.data.split(":")[-1])

    stmt = select(User).where(User.tg_id == callback.from_user.id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    repo = OrdersRepo(session)
    active_orders = await repo.get_user_active_orders(user.id)
    target_order = next((order for order in active_orders if order.id == order_id), None)
    if not target_order:
        await callback.answer("Заказ уже недоступен для отмены", show_alert=True)
        return

    ok = await repo.cancel_order(order_id)
    if not ok:
        await callback.answer("Не удалось отменить заказ", show_alert=True)
        return

    await session.commit()
    try:
        await callback.message.edit_text(
            f"🗑 <b>Заказ #{order_id} отменён.</b>\nТовары возвращены на склад.",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer("Заказ отменён")

# ---------- Текстовое меню ----------

@client_router.message(F.text.in_([settings.button_catalog, "📦 Каталог", "🏪 Витрина"]))
async def menu_catalog_text(message: Message, session: AsyncSession):
    await cmd_catalog(message, session)

@client_router.message(F.text == settings.button_cart)
async def menu_cart_text(message: Message, session: AsyncSession):
    await cmd_cart(message, session)

@client_router.callback_query(F.data == "ai_open_catalog")
async def cb_open_catalog_from_ai(callback: CallbackQuery, session: AsyncSession):
    await callback.answer("Открываю витрину...")
    await cmd_catalog(callback.message, session)