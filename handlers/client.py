from __future__ import annotations

import asyncio
from datetime import datetime

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
from models import Category, Brand, Product, User, CartItem, UserRole
from models.users import normalize_role

client_router = Router()

# ---------- FSM (Машина состояний) ----------

class ClientStates(StatesGroup):
    # Состояние для добавления в корзину
    waiting_for_size = State()
    
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
            [KeyboardButton(text="🛍 Каталог"), KeyboardButton(text="🛒 Корзина")],
            [KeyboardButton(text="📦 Мои заказы"), KeyboardButton(text="✨ AI-Консультант")],
            [KeyboardButton(text="💬 Поддержка")],
        ],
        resize_keyboard=True,
    )


def _is_back_text(text: str | None) -> bool:
    return text in {"⬅ Назад", "🔙 Назад", "❌ Отмена", "🏠 Меню"}


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

def build_categories_kb(categories: list[Category]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for c in categories:
        kb.button(text=c.name, callback_data=f"cat:{c.id}")
    kb.adjust(1)
    return kb

def build_brands_kb(
    category_id: int,
    brands: list[Brand],
    page: int,
    total_count: int,
    page_size: int,
) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for b in brands:
        kb.button(text=b.name, callback_data=f"brand:{category_id}:{b.id}")

    total_pages = (total_count + page_size - 1) // page_size
    nav_count = 0
    if page > 1:
        kb.button(text="⬅️", callback_data=f"brandpage:{category_id}:{page-1}")
        nav_count += 1
    kb.button(text=f"{page}/{total_pages}", callback_data="ignore")
    nav_count += 1
    if page < total_pages:
        kb.button(text="➡️", callback_data=f"brandpage:{category_id}:{page+1}")
        nav_count += 1

    kb.button(text="⬅ Назад", callback_data="back:categories")

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
    if items:
        kb.button(text="✅ Оформить заказ", callback_data="order:start")
    
    for it in items:
        title = it.product.title if it.product else f"ID {it.product_id}"
        sku = it.product.sku if it.product else None
        title_with_sku = f"{title} [{sku}]" if sku else title
        kb.button(text=f"🗑 Удалить: {title_with_sku} ({it.size})", callback_data=f"cart:del:{it.id}")
    
    kb.button(text="⬅ В каталог", callback_data="back:categories")
    kb.adjust(1)
    return kb


# ---------- Команды (Меню) ----------

@client_router.message(Command("catalog"))
async def cmd_catalog(message: Message, session: AsyncSession) -> None:
    repo = CatalogRepo(session)
    categories = await repo.list_categories()

    if not categories:
        await message.answer("Категории пока не созданы.")
        return

    kb = build_categories_kb(list(categories))
    await message.answer("Выбери категорию:", reply_markup=kb.as_markup())


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


@client_router.message(F.text == "💬 Поддержка")
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
        user = User(
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            role=UserRole.CLIENT.value,
            ai_quota=settings.ai_client_start_quota,
        )
        session.add(user)
        await session.commit()

    staff_stmt = select(User.tg_id).where(User.role == UserRole.STAFF.value)
    staff_res = await session.execute(staff_stmt)
    staff_ids = [sid for sid in staff_res.scalars().all() if sid]
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
        await message.bot.send_message(
            chat_id=settings.owner_id,
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
        user = User(
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            role=UserRole.CLIENT.value,
            ai_quota=settings.ai_client_start_quota,
        )
        session.add(user)
        await session.commit()

    username_line = f"@{user.username}" if user.username else "—"
    info_text = (
        f"💬 Сообщение от клиента:\n"
        f"👤 {user.full_name}\n"
        f"🆔 {user.tg_id}\n"
        f"{username_line}"
    )

    kb = _build_support_reply_kb(user.tg_id, can_block=True, is_blocked=bool(user.is_blocked))
    try:
        await message.bot.forward_message(
            chat_id=settings.owner_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        await message.bot.send_message(
            chat_id=settings.owner_id,
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
        user = User(
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            role=UserRole.CLIENT.value,
            ai_quota=settings.ai_client_start_quota,
        )
        session.add(user)
        await session.commit()

    username_line = f"@{user.username}" if user.username else "—"
    info_text = (
        f"💬 Сообщение от клиента:\n"
        f"👤 {user.full_name}\n"
        f"🆔 {user.tg_id}\n"
        f"{username_line}"
    )

    staff_stmt = select(User.tg_id).where(User.role == UserRole.STAFF.value)
    staff_res = await session.execute(staff_stmt)
    staff_ids = [sid for sid in staff_res.scalars().all() if sid and sid != settings.owner_id]

    kb_owner = _build_support_reply_kb(user.tg_id, can_block=True, is_blocked=bool(user.is_blocked))
    kb_staff = _build_support_reply_kb(user.tg_id, can_block=False, is_blocked=False)

    staff_delivered = 0
    targets = [settings.owner_id, *staff_ids]
    for target_id in targets:
        try:
            await message.bot.send_message(
                chat_id=target_id,
                text=info_text,
                reply_markup=(kb_owner if target_id == settings.owner_id else kb_staff).as_markup(),
            )
            await message.bot.copy_message(
                chat_id=target_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            if target_id != settings.owner_id:
                staff_delivered += 1
        except Exception:
            continue

    if staff_ids and staff_delivered == 0:
        await message.bot.send_message(
            chat_id=settings.owner_id,
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
        user = User(
            tg_id=user_id,
            username=username,
            first_name=first_name,
            role=UserRole.CLIENT.value,
        )
        session.add(user)
        await session.commit()

    orders_repo = OrdersRepo(session)
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
        lines.append(
            f"▫️ <b>{brand_name}</b> | {product_title}\n"
            f"{sku_line}"
            f"   Размер: {it.size} | {it.quantity} шт. x {it.price_at_add} ₽"
        )

    lines.append(f"\n💰 <b>Итого: {total} ₽</b>")

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
    category_id = int(callback.data.split(":")[1])

    repo = CatalogRepo(session)
    cat = await session.get(Category, category_id)
    if not cat:
        await callback.answer("Категория не найдена")
        return

    total_count = await repo.count_brands_by_category(category_id)
    if total_count == 0:
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
        return

    await show_brands_page(callback, session, category_id, page=1)
    await callback.answer()
    return

@client_router.callback_query(F.data.startswith("brandpage:"))
async def cq_brand_page(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    category_id = int(parts[1])
    page = int(parts[2])
    await show_brands_page(callback, session, category_id, page)

async def show_brands_page(
    callback: CallbackQuery,
    session: AsyncSession,
    category_id: int,
    page: int,
) -> None:
    PAGE_SIZE = 8
    repo = CatalogRepo(session)
    cat = await session.get(Category, category_id)
    total_count = await repo.count_brands_by_category(category_id)

    if not cat or total_count == 0:
        await callback.answer("Категории пока нет брендов", show_alert=True)
        return

    brands = await repo.get_brands_by_category_paginated(category_id, page, PAGE_SIZE)
    kb = build_brands_kb(category_id, list(brands), page, total_count, PAGE_SIZE)
    text = f"📂 Категория: <b>{cat.name}</b>\nВыберите бренд:"

    if callback.message.photo:
        await callback.message.delete()
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
    
    repo = CatalogRepo(session)
    
    products = await repo.get_products_by_category_brand_paginated(cat_id, brand_id, page, PAGE_SIZE)
    total_count = await repo.count_products_by_category_brand(cat_id, brand_id)
    
    brand = await session.get(Brand, brand_id)
    brand_name = brand.name if brand else "Бренд"

    if not products and page == 1:
        await callback.message.edit_text(f"В бренде {brand_name} пока нет товаров.")
        return

    kb = build_products_kb(cat_id, brand_id, list(products), page, total_count, PAGE_SIZE)
    
    text = f"🏷 Бренд: <b>{brand_name}</b>\nВыберите модель:"

    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        try:
            await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        except Exception:
            pass
            
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

        repo = CatalogRepo(session)
        product = await repo.get_product_with_details(product_id)
    except Exception as e:
        await callback.answer("Ошибка обработки запроса. Проверьте логи.", show_alert=True)
        return

    if not product:
        await callback.answer("Товар не найден.", show_alert=True)
        return

    stmt = select(User).where(User.tg_id == callback.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    is_staff = user is not None and normalize_role(user.role) == UserRole.STAFF.value

    available_sizes = [f"{s.size}" for s in product.stock if s.quantity > 0]
    sizes_str = ", ".join(available_sizes) if available_sizes else "Нет в наличии"
    stock_details = ", ".join(
        [f"{s.size} ({s.quantity})" for s in product.stock if s.quantity > 0]
    )

    brand_name = product.brand.name if product.brand else "Бренд не указан"
    text = (
        f"🏷 {product.title}\n"
        f"🏷️ Бренд: {brand_name}\n"
        f"🔖 SKU: {product.sku}\n\n"
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
    
    kb.button(text="⬅ Назад", callback_data=f"back:products:{category_id}:{brand_id}")
    kb.adjust(1)

    try:
        await callback.message.delete()
    except:
        pass

    if product.photos:
        if len(product.photos) > 1:
            album = MediaGroupBuilder(caption=text)
            for ph in product.photos:
                album.add_photo(media=ph.file_id)
            
            await callback.message.answer_media_group(media=album.build())
            await callback.message.answer("👇 Действия:", reply_markup=kb.as_markup())
            
        else:
            await callback.message.answer_photo(
                photo=product.photos[0].file_id,
                caption=text,
                reply_markup=kb.as_markup()
            )
    else:
        await callback.message.answer(text, reply_markup=kb.as_markup())
    
    await callback.answer()


# ---------- Кнопки "Назад" ----------

@client_router.callback_query(F.data == "back:categories")
async def cq_back_categories(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.message.delete()
    await cmd_catalog(callback.message, session)

@client_router.callback_query(F.data == "catalog_start")
async def cq_catalog_start(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.message.delete()
    await cmd_catalog(callback.message, session)

@client_router.callback_query(F.data == "ignore")
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
    data = await state.get_data()
    product_id = data.get("product_id")

    stmt = select(User).where(User.tg_id == message.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    product = await session.get(Product, product_id)

    if user and product:
        orders_repo = OrdersRepo(session)
        await orders_repo.add_to_cart(user, product, size, 1)
        await session.commit()
        
        await message.answer(
            f"✅ Товар <b>{product.title}</b> (размер {size}) добавлен в корзину!",
            parse_mode="HTML"
        )
        
        kb = InlineKeyboardBuilder()
        kb.button(text="🛒 Перейти в корзину", callback_data="show:cart")
        kb.button(text="🛍 Продолжить покупки", callback_data="back:categories")
        await message.answer("Что дальше?", reply_markup=kb.as_markup())
    else:
        await message.answer("Ошибка добавления. Попробуйте снова /catalog")

    await state.clear()


# ---------- Управление корзиной ----------

@client_router.callback_query(F.data == "show:cart")
async def cq_show_cart_cb(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.message.delete()
    await show_cart_for(
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
        message=callback.message,
        session=session,
    )

@client_router.callback_query(F.data.startswith("cart:del:"))
async def cq_cart_del(callback: CallbackQuery, session: AsyncSession) -> None:
    item_id = int(callback.data.split(":")[2])
    
    stmt = select(User).where(User.tg_id == callback.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    orders_repo = OrdersRepo(session)
    await orders_repo.delete_cart_item(user, item_id)
    await session.commit()

    await callback.answer("Удалено")
    await cq_show_cart_cb(callback, session)


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
        admin_text = (
            f"🔔 <b>НОВЫЙ ЗАКАЗ #{order.id}</b>\n"
            f"👤 Клиент: {full_name} (@{message.from_user.username})\n"
            f"📱 Телефон: {phone}\n"
            f"💰 Сумма: {order.total_price} ₽\n\n"
            f"📦 <b>Состав заказа:</b>\n"
            f"{items_list_text}"
        )
        await bot.send_message(settings.owner_id, admin_text, parse_mode="HTML")
        staff_stmt = select(User.tg_id).where(User.role == UserRole.STAFF.value)
        staff_res = await session.execute(staff_stmt)
        staff_ids = staff_res.scalars().all()
        for staff_id in staff_ids:
            if staff_id in (settings.owner_id, message.from_user.id):
                continue
            try:
                await bot.send_message(staff_id, admin_text, parse_mode="HTML")
            except Exception:
                continue
    except Exception as e:
        print(f"Ошибка отправки уведомления владельцу: {e}")

    await state.clear()

@client_router.message(F.text == "📦 Мои заказы")
async def cmd_my_orders_history(message: Message, session: AsyncSession) -> None:
    stmt = select(User).where(User.tg_id == message.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    if not user:
        await message.answer("Сначала нажмите /start")
        return

    repo = OrdersRepo(session)
    orders = await repo.get_user_completed_orders(user.id)

    if not orders:
        await message.answer("📭 У вас пока нет завершенных покупок.")
        return

    await message.answer(f"📦 <b>История ваших покупок ({len(orders)} шт.):</b>", parse_mode="HTML")

    for order in orders:
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
        
        await message.answer(msg_text, parse_mode="HTML")
        await asyncio.sleep(0.1)

# ---------- Текстовое меню ----------

@client_router.message(F.text.in_(["🛍 Каталог", "📦 Каталог", "🏪 Витрина"]))
async def menu_catalog_text(message: Message, session: AsyncSession):
    await cmd_catalog(message, session)

@client_router.message(F.text == "🛒 Корзина")
async def menu_cart_text(message: Message, session: AsyncSession):
    await cmd_cart(message, session)

@client_router.callback_query(F.data == "ai_open_catalog")
async def cb_open_catalog_from_ai(callback: CallbackQuery, session: AsyncSession):
    await callback.answer("Открываю витрину...")
    await cmd_catalog(callback.message, session)