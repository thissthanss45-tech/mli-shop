from __future__ import annotations

from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.catalog_repo import CatalogRepo
from models import Category, Brand, Product, ProductStock
from .owner_states import EditProductStates
from .owner_utils import ensure_owner

# Создаем новый роутер для склада
warehouse_router = Router(name="owner_warehouse")

# ==========================================
# 📊 1. ГЛАВНЫЙ ДАШБОРД (СВОДКА + БЫСТРЫЕ ФИЛЬТРЫ)
# ==========================================

@warehouse_router.message(F.text == "📊 Склад")
async def warehouse_dashboard(message: Message, session: AsyncSession):
    if not await ensure_owner(message, session): 
        return

    await send_warehouse_dashboard(message, session)


async def send_warehouse_dashboard(message: Message, session: AsyncSession) -> None:
    repo = CatalogRepo(session)
    products = await repo.get_all_products_with_stock()
    categories = await repo.list_categories()

    if not products:
        await message.answer("📭 Склад пуст. Добавьте товары через меню «📦 Товары».")
        return

    # Считаем деньги
    total_items = 0
    total_purchase_sum = 0.0
    total_sale_sum = 0.0

    for p in products:
        qty = sum(s.quantity for s in p.stock)
        total_items += qty
        total_purchase_sum += float(p.purchase_price) * qty
        total_sale_sum += float(p.sale_price) * qty

    potential_profit = total_sale_sum - total_purchase_sum

    text = (
        f"🏛 <b>ФИНАНСОВЫЙ ОТЧЕТ</b>\n\n"
        f"📦 Всего товаров: <b>{total_items}</b> шт.\n"
        f"🔴 В закупке: <b>{total_purchase_sum:,.0f}</b> ₽\n"
        f"🟢 В продаже: <b>{total_sale_sum:,.0f}</b> ₽\n"
        f"📈 Потенциальная прибыль: <b>{potential_profit:,.0f}</b> ₽\n\n"
        f"<b>➡️ Выберите действие:</b>"
    )

    kb = InlineKeyboardBuilder()
    
    # Быстрые фильтры
    kb.button(text="🚨 Критические остатки", callback_data="wh:filter:critical")
    kb.button(text="📈 Топ по марже", callback_data="wh:filter:margin")
    kb.button(text="⚪️ Нулевой остаток", callback_data="wh:filter:zero")
    kb.button(text="🆕 Новые товары", callback_data="wh:filter:new")
    
    kb.button(text="📂 По категориям", callback_data="wh:filter:categories")
    kb.button(text="❌ Закрыть", callback_data="owner:cancel")
    kb.adjust(2, 2, 1, 1)

    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


# ==========================================
# ⚡ БЫСТРЫЕ ФИЛЬТРЫ
# ==========================================

@warehouse_router.callback_query(F.data == "wh:filter:critical")
async def filter_critical_stock(callback: CallbackQuery, session: AsyncSession):
    repo = CatalogRepo(session)
    products = await repo.get_critical_stock_products(limit=15)
    
    if not products:
        await callback.answer("✅ Критических остатков не найдено!", show_alert=True)
        return
    
    text = "🚨 <b>ТОВАРЫ С КРИТИЧЕСКИМ ОСТАТКОМ (≤5 шт)</b>\n\n"
    
    kb = InlineKeyboardBuilder()
    for p in products:
        qty = sum(s.quantity for s in p.stock)
        kb.button(text=f"{p.title} ({qty}⚠️)", callback_data=f"wh:prod:{p.id}")
    kb.button(text="🔙 Назад", callback_data="wh:back_to_dash")
    kb.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@warehouse_router.callback_query(F.data == "wh:filter:margin")
async def filter_top_margin(callback: CallbackQuery, session: AsyncSession):
    repo = CatalogRepo(session)
    products = await repo.get_top_margin_products(limit=5)
    
    if not products:
        await callback.answer("Товаров не найдено", show_alert=True)
        return
    
    text = "📈 <b>ТОП-5 ТОВАРОВ ПО МАРЖЕ</b>\n\n"
    
    kb = InlineKeyboardBuilder()
    for p in products:
        margin = float(p.sale_price) - float(p.purchase_price)
        kb.button(text=f"{p.title} (+{margin:g}₽)", callback_data=f"wh:prod:{p.id}")
    kb.button(text="🔙 Назад", callback_data="wh:back_to_dash")
    kb.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@warehouse_router.callback_query(F.data == "wh:filter:zero")
async def filter_zero_stock(callback: CallbackQuery, session: AsyncSession):
    repo = CatalogRepo(session)
    products = await repo.get_zero_stock_products(limit=15)
    
    if not products:
        await callback.answer("✅ Нет товаров с нулевым остатком!", show_alert=True)
        return
    
    text = "⚪️ <b>ТОВАРЫ БЕЗ ОСТАТКОВ</b>\n\n"
    
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(text=f"{p.title}", callback_data=f"wh:prod:{p.id}")
    kb.button(text="🔙 Назад", callback_data="wh:back_to_dash")
    kb.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@warehouse_router.callback_query(F.data == "wh:filter:new")
async def filter_new_products(callback: CallbackQuery, session: AsyncSession):
    await show_new_products_page(callback, session, page=1)
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:newpage:"))
async def filter_new_products_page(callback: CallbackQuery, session: AsyncSession):
    page = int(callback.data.split(":")[2])
    await show_new_products_page(callback, session, page=page)
    await callback.answer()


async def show_new_products_page(callback: CallbackQuery, session: AsyncSession, page: int) -> None:
    PAGE_SIZE = 8
    repo = CatalogRepo(session)
    total_count = await repo.count_new_products(days=7)
    if total_count == 0:
        await callback.answer("Новых товаров не найдено", show_alert=True)
        return

    products = await repo.get_new_products_paginated(days=7, page=page, page_size=PAGE_SIZE)
    total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE
    if page < 1 or page > total_pages:
        await callback.answer("Страница не найдена", show_alert=True)
        return

    text = f"🆕 <b>НОВЫЕ ТОВАРЫ (за 7 дней)</b>\nСтраница {page}/{total_pages}\n\n"

    kb = InlineKeyboardBuilder()
    for p in products:
        qty = sum(s.quantity for s in p.stock)
        now = datetime.utcnow()
        days_ago = (now - p.created_at).days
        kb.button(text=f"{p.title} ({qty} шт, {days_ago}д назад)", callback_data=f"wh:prod:{p.id}")

    nav_count = 0
    if page > 1:
        kb.button(text="⬅️", callback_data=f"wh:newpage:{page-1}")
        nav_count += 1
    kb.button(text=f"{page}/{total_pages}", callback_data="ignore")
    nav_count += 1
    if page < total_pages:
        kb.button(text="➡️", callback_data=f"wh:newpage:{page+1}")
        nav_count += 1

    kb.button(text="🔙 Назад", callback_data="wh:back_to_dash")

    layout = [1] * max(1, len(products))
    layout.append(max(1, nav_count))
    layout.append(1)
    kb.adjust(*layout)

    if callback.message.photo:
        try:
            await callback.message.edit_caption(
                caption=text,
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception:
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@warehouse_router.callback_query(F.data == "wh:filter:categories")
async def filter_by_categories(callback: CallbackQuery, session: AsyncSession):
    repo = CatalogRepo(session)
    categories = await repo.list_categories()
    
    text = "📂 <b>КАТЕГОРИИ</b>\n\n"
    
    kb = InlineKeyboardBuilder()
    for c in categories:
        stats = await repo.get_category_stats(c.id)
        text_btn = f"📂 {c.name} ({stats['product_count']} товаров, {stats['total_items']} шт)"
        kb.button(text=text_btn, callback_data=f"wh:cat:{c.id}")
    kb.button(text="🔙 Назад", callback_data="wh:back_to_dash")
    kb.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@warehouse_router.callback_query(F.data == "wh:back_to_dash")
async def back_to_dashboard(callback: CallbackQuery, session: AsyncSession):
    if not await ensure_owner(callback, session):
        return
    await callback.message.delete()
    await send_warehouse_dashboard(callback.message, session)


# ==========================================
# 📂 2. НАВИГАЦИЯ (Категория -> Бренд)
# ==========================================

@warehouse_router.callback_query(F.data.startswith("wh:cat:"))
async def warehouse_show_brands(callback: CallbackQuery, session: AsyncSession):
    cat_id = int(callback.data.split(":")[2])
    await show_brands_page(callback, session, cat_id, page=1)
    await callback.answer()
    return

@warehouse_router.callback_query(F.data.startswith("wh:brandpage:"))
async def warehouse_brands_page(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    cat_id = int(parts[2])
    page = int(parts[3])
    await show_brands_page(callback, session, cat_id, page)

async def show_brands_page(callback: CallbackQuery, session: AsyncSession, cat_id: int, page: int) -> None:
    PAGE_SIZE = 8
    repo = CatalogRepo(session)

    cat = await session.get(Category, cat_id)
    total_count = await repo.count_brands_by_category(cat_id)
    if not cat or total_count == 0:
        await callback.answer("В этой категории нет брендов с товарами.", show_alert=True)
        return

    brands = await repo.get_brands_by_category_paginated(cat_id, page, PAGE_SIZE)

    kb = InlineKeyboardBuilder()
    for b in brands:
        stats = await repo.get_brand_stats(b.id, cat_id)
        btn_text = (
            f"🏷 {b.name}\n"
            f"  {stats['product_count']} товаров | "
            f"{stats['total_items']} шт | "
            f"{stats['total_investment']:,.0f}₽"
        )
        kb.button(text=btn_text, callback_data=f"wh:brand:{cat_id}:{b.id}")

    total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE
    nav_count = 0
    if page > 1:
        kb.button(text="⬅️", callback_data=f"wh:brandpage:{cat_id}:{page-1}")
        nav_count += 1
    kb.button(text=f"{page}/{total_pages}", callback_data="ignore")
    nav_count += 1
    if page < total_pages:
        kb.button(text="➡️", callback_data=f"wh:brandpage:{cat_id}:{page+1}")
        nav_count += 1

    kb.button(text="🔙 Назад", callback_data="wh:back_to_dash")

    layout = [1] * max(1, len(brands))
    layout.append(max(1, nav_count))
    layout.append(1)
    kb.adjust(*layout)

    text = f"📂 Категория: <b>{cat.name}</b>\nВыберите бренд:"

    if callback.message.photo:
        try:
            await callback.message.edit_caption(
                caption=text,
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception:
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


# ==========================================
# 🏷 3. СПИСОК ТОВАРОВ (Бренд -> Товары с сортировкой)
# ==========================================

@warehouse_router.callback_query(F.data.startswith("wh:brand:"))
async def warehouse_show_products(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    parts = callback.data.split(":")
    cat_id = int(parts[2])
    brand_id = int(parts[3])
    
    # Сохраняем контекст для сортировки
    await state.update_data(current_cat_id=cat_id, current_brand_id=brand_id, current_sort="name")

    repo = CatalogRepo(session)
    brand = await session.get(Brand, brand_id)
    
    await show_products_list(callback, session, cat_id, brand_id, "name")

async def show_products_list(callback: CallbackQuery, session: AsyncSession, cat_id: int, brand_id: int, sort_by: str):
    repo = CatalogRepo(session)
    products = await repo.get_products_sorted(cat_id, brand_id, sort_by)
    brand = await session.get(Brand, brand_id)

    if not products:
        await callback.answer("Товаров не найдено", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    
    # Товары
    for p in products:
        total_qty = sum(s.quantity for s in p.stock)
        # Определяем статус по остаткам
        if total_qty == 0:
            status = "⚪️"
        elif total_qty <= 5:
            status = "🔴"
        elif total_qty <= 20:
            status = "🟡"
        else:
            status = "🟢"
        
        kb.button(text=f"{status} {p.title} ({total_qty} шт)", callback_data=f"wh:prod:{p.id}")
    
    # Сортировка
    sort_names = {"name": "По названию", "price": "По цене", "margin": "По марже", "stock": "По остаткам"}
    kb.button(text=f"↕️ Сортировка: {sort_names.get(sort_by, sort_by)}", callback_data="wh:sort_menu")
    kb.button(text="🔙 Назад", callback_data=f"wh:cat:{cat_id}")
    kb.adjust(1, 1, 1)

    text = (
        f"🏷 Бренд: <b>{brand.name}</b>\n"
        f"Выберите товар (сортировка: {sort_names.get(sort_by, sort_by)}):"
    )

    if callback.message.photo:
        try:
            await callback.message.edit_caption(
                caption=text,
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception:
            await callback.message.delete()
            await callback.message.answer(
                text,
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
    else:
        await callback.message.edit_text(
            text,
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )

@warehouse_router.callback_query(F.data == "wh:sort_menu")
async def show_sort_menu(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 По названию", callback_data="wh:sort:name")
    kb.button(text="💰 По цене", callback_data="wh:sort:price")
    kb.button(text="📈 По марже", callback_data="wh:sort:margin")
    kb.button(text="📦 По остаткам", callback_data="wh:sort:stock")
    kb.button(text="❌ Отмена", callback_data="wh:sort_cancel")
    kb.adjust(2, 2, 1)
    
    text = "↕️ <b>Выберите способ сортировки:</b>"

    if callback.message.photo:
        try:
            await callback.message.edit_caption(
                caption=text,
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception:
            await callback.message.delete()
            await callback.message.answer(
                text,
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
    else:
        await callback.message.edit_text(
            text,
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
    await callback.answer()

@warehouse_router.callback_query(F.data.startswith("wh:sort:"))
async def apply_sort(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    sort_type = callback.data.split(":")[2]
    data = await state.get_data()
    
    await state.update_data(current_sort=sort_type)
    await show_products_list(callback, session, data["current_cat_id"], data["current_brand_id"], sort_type)
    await callback.answer()

@warehouse_router.callback_query(F.data == "wh:sort_cancel")
async def cancel_sort(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    sort_by = data.get("current_sort", "name")
    await show_products_list(callback, session, data["current_cat_id"], data["current_brand_id"], sort_by)
    await callback.answer()


# ==========================================
# 🛠 4. КАРТОЧКА ТОВАРА (Улучшенная)
# ==========================================

@warehouse_router.callback_query(F.data.startswith("wh:prod:"))
async def warehouse_product_card(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    # Если вызов идет из функции обновления (после редактирования)
    if isinstance(callback, Message):
        # Хак, чтобы работало и от Message
        product_id = (await state.get_data()).get("product_id")
        message = callback
    else:
        product_id = int(callback.data.split(":")[2])
        await state.update_data(product_id=product_id)
        message = callback.message

    repo = CatalogRepo(session)
    p = await repo.get_product_with_details(product_id)

    if not p:
        if isinstance(callback, CallbackQuery): 
            await callback.answer("Товар не найден")
        return

    # Сбор данных
    total_qty = sum(s.quantity for s in p.stock)
    sizes_str = ", ".join([f"{s.size} ({s.quantity})" for s in p.stock if s.quantity > 0]) or "Нет"
    margin = float(p.sale_price) - float(p.purchase_price)
    
    # Статус остатка
    if total_qty == 0:
        stock_status = "⚪️ Нет в наличии"
    elif total_qty <= 5:
        stock_status = f"🔴 Критический ({total_qty} шт)"
    elif total_qty <= 20:
        stock_status = f"🟡 Низкий ({total_qty} шт)"
    else:
        stock_status = f"🟢 Хороший ({total_qty} шт)"
    
    # Обрезанное описание
    description = p.description or "Пусто"
    if len(description) > 100:
        description = description[:97] + "..."
    
    # Дата добавления
    now = datetime.utcnow()
    days_ago = (now - p.created_at).days
    date_str = f"{days_ago}д назад" if days_ago > 0 else "Сегодня"
    
    text = (
        f"🛠 <b>УПРАВЛЕНИЕ ТОВАРОМ #{p.id}</b>\n\n"
        f"🏷 <b>{p.title}</b>\n"
        f"🏷️ Бренд: {p.brand.name if p.brand else 'Бренд не указан'}\n"
        f"🔖 SKU: <code>{p.sku}</code>\n"
        f"📅 Добавлен: {date_str}\n\n"
        f"<b>📊 ОСТАТКИ</b>\n"
        f"Статус: {stock_status}\n"
        f"Размеры: {sizes_str}\n\n"
        f"<b>💰 ФИНАНСЫ</b>\n"
        f"Цена продажи: <b>{p.sale_price:g}₽</b>\n"
        f"Цена закупки: <b>{p.purchase_price:g}₽</b>\n"
        f"Маржа за ед.: <b>+{margin:g}₽</b>\n"
        f"Маржа всего: <b>+{margin * total_qty:,.0f}₽</b>\n\n"
        f"<b>📝 Описание</b>\n{description}"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Изм. Цену", callback_data="edit:price")
    kb.button(text="📦 Изм. Остаток", callback_data="edit:stock")
    kb.button(text="📝 Изм. Описание", callback_data="edit:desc")
    kb.button(text="🔙 Назад", callback_data=f"wh:brand:{p.category_id}:{p.brand_id}")
    kb.adjust(2, 1, 1)

    # Отправка (учитываем фото)
    if p.photos:
        if message.photo:
            await message.edit_caption(caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
        else:
            await message.delete()
            await message.answer_photo(p.photos[0].file_id, caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        if message.photo:
            await message.delete()
            await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        else:
            await message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


# ==========================================
# ✏️ 5. ЛОГИКА РЕДАКТИРОВАНИЯ
# ==========================================

# --- ЦЕНА ---
@warehouse_router.callback_query(F.data == "edit:price")
async def edit_price_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductStates.edit_price)
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data="wh:prod_back")
    kb.button(text="❌ Отмена", callback_data="owner:cancel")
    kb.adjust(2)
    await callback.message.answer(
        "Введите новые цены через пробел:\nFormat: <code>ЗАКУПКА ПРОДАЖА</code>\nПример: <code>25000 45000</code>", 
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()

@warehouse_router.callback_query(F.data == "wh:prod_back")
async def edit_price_back(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await callback.answer()
    await warehouse_product_card(callback.message, session, state)

@warehouse_router.message(EditProductStates.edit_price)
async def edit_price_process(message: Message, state: FSMContext, session: AsyncSession):
    try:
        parts = message.text.split()
        new_purchase = float(parts[0])
        new_sale = float(parts[1])
        
        data = await state.get_data()
        repo = CatalogRepo(session)
        await repo.update_product_prices(data["product_id"], new_purchase, new_sale)
        await session.commit()

        await message.answer("✅ Цены обновлены.")
        await warehouse_product_card(message, session, state) # Возврат в карточку
    except:
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 Назад", callback_data="wh:prod_back")
        kb.button(text="❌ Отмена", callback_data="owner:cancel")
        kb.adjust(2)
        await message.answer(
            "❌ Ошибка. Введите два числа через пробел (ЗАКУП ПРОДАЖА).",
            reply_markup=kb.as_markup(),
        )

# --- ОСТАТКИ ---
@warehouse_router.callback_query(F.data == "edit:stock")
async def edit_stock_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    repo = CatalogRepo(session)
    p = await repo.get_product_with_details(data["product_id"])
    
    kb = InlineKeyboardBuilder()
    for s in p.stock:
        kb.button(text=f"{s.size} (сейчас: {s.quantity})", callback_data=f"stock:size:{s.size}")
    kb.button(text="➕ Добавить новый размер", callback_data="stock:new")
    kb.button(text="❌ Отмена", callback_data="owner:cancel")
    kb.adjust(1)
    
    await callback.message.answer("Какой размер редактируем?", reply_markup=kb.as_markup())
    await callback.answer()

@warehouse_router.callback_query(F.data.startswith("stock:size:"))
async def edit_stock_choice(callback: CallbackQuery, state: FSMContext):
    size = callback.data.split(":")[-1]
    await state.update_data(editing_size=size)
    await state.set_state(EditProductStates.edit_stock_qty)
    await callback.message.answer(f"Введите новое количество для размера {size}:")

@warehouse_router.callback_query(F.data == "stock:new")
async def edit_stock_new(callback: CallbackQuery, state: FSMContext):
    await state.update_data(editing_size=None)
    await state.set_state(EditProductStates.edit_stock_qty)
    await callback.message.answer("Введите: РАЗМЕР КОЛИЧЕСТВО (Пример: <code>44 5</code>)", parse_mode="HTML")

@warehouse_router.message(EditProductStates.edit_stock_qty)
async def edit_stock_process(message: Message, state: FSMContext, session: AsyncSession):
    text = message.text.strip()
    data = await state.get_data()
    pid = data["product_id"]
    repo = CatalogRepo(session)

    try:
        if data.get("editing_size"):
            # Обновляем старый
            qty = int(text)
            await repo.update_stock_quantity(pid, data["editing_size"], qty)
        else:
            # Создаем новый
            parts = text.split()
            size, qty = parts[0], int(parts[1])
            await repo.update_stock_quantity(pid, size, qty)
        
        await session.commit()
        await message.answer("✅ Остатки обновлены.")
        await warehouse_product_card(message, session, state)
    except:
        await message.answer("❌ Ошибка формата. Попробуйте еще раз.")

# --- ОПИСАНИЕ ---
@warehouse_router.callback_query(F.data == "edit:desc")
async def edit_desc_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductStates.edit_description)
    await callback.message.answer("Введите новое описание (или '-' чтобы удалить):")
    await callback.answer()

@warehouse_router.message(EditProductStates.edit_description)
async def edit_desc_process(message: Message, state: FSMContext, session: AsyncSession):
    desc = message.text.strip()
    if desc == "-": 
        desc = None
    
    data = await state.get_data()
    repo = CatalogRepo(session)
    await repo.update_product_description(data["product_id"], desc)
    await session.commit()
    
    await message.answer("✅ Описание обновлено.")
    await warehouse_product_card(message, session, state)