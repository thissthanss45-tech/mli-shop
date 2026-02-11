from __future__ import annotations

import asyncio

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, InlineKeyboardButton
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


# ---------- Клавиатуры ----------

def build_categories_kb(categories: list[Category]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for c in categories:
        kb.button(text=c.name, callback_data=f"cat:{c.id}")
    kb.adjust(1)
    return kb

def build_brands_kb(category_id: int, brands: list[Brand]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for b in brands:
        kb.button(text=b.name, callback_data=f"brand:{category_id}:{b.id}")
    kb.button(text="⬅ Назад", callback_data="back:categories")
    kb.adjust(1)
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
        kb.button(text=f"🗑 Удалить: {title} ({it.size})", callback_data=f"cart:del:{it.id}")
    
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

        lines.append(
            f"▫️ <b>{brand_name}</b> | {product_title}\n"
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

    brands = await repo.get_brands_by_category(category_id)

    if not brands:
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

    kb = build_brands_kb(category_id, list(brands))
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

    text = (
        f"🏷 {product.title}\n\n"
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
    category_id = int(callback.data.split(":")[2])

    repo = CatalogRepo(session)
    cat = await session.get(Category, category_id)
    if not cat:
        await callback.answer("Категория не найдена")
        return

    brands = await repo.get_brands_by_category(category_id)
    
    if not brands:
        await callback.message.edit_text("В этой категории пока нет брендов.")
        return

    kb = build_brands_kb(category_id, list(brands))
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(
            f"📂 Категория: <b>{cat.name}</b>\nВыберите бренд:",
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            f"📂 Категория: <b>{cat.name}</b>\nВыберите бренд:",
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
    await callback.answer()

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

    await orders_repo.clear_cart(user)
    await session.commit()

    await message.answer(f"✅ <b>Заказ #{order.id} оформлен!</b>\nМенеджер свяжется с вами.", parse_mode="HTML")
    
    items_list_text = ""
    for it in cart_items:
        brand = it.product.brand.name if (it.product and it.product.brand) else ""
        title = it.product.title if it.product else "???"
        items_list_text += f"— {brand} {title} ({it.size}) x{it.quantity}\n"

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
                name_str = f"{brand} {title}"
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