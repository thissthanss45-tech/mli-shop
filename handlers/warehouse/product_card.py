from __future__ import annotations

from datetime import datetime

from aiogram import F
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.catalog_repo import CatalogRepo
from models import Category, Brand, Order, OrderItem, OrderStatus
from ..owner_states import EditProductStates
from ..owner_utils import ensure_owner, owner_only, show_owner_main_menu
from .common import warehouse_router


_EXIT_TEXTS = {"⬅ Назад", "🔙 Назад", "↩️ Назад", "↩️ Отмена", "Отмена", "🧭 В меню", "🏠 Меню"}


def _parse_warehouse_product_callback(callback_data: str) -> tuple[int, bool, int | None]:
    parts = callback_data.split(":")
    if len(parts) < 3 or parts[0] != "wh" or parts[1] != "prod":
        raise ValueError("Invalid warehouse product callback format")

    product_id = int(parts[2])
    opened_from_procurement = len(parts) > 3 and parts[3] == "proc"
    procurement_qty = None
    if opened_from_procurement and len(parts) > 4 and parts[4].isdigit():
        procurement_qty = int(parts[4])

    return product_id, opened_from_procurement, procurement_qty


@warehouse_router.callback_query(F.data.startswith("wh:cat:"))
@owner_only
async def warehouse_show_brands(callback: CallbackQuery, session: AsyncSession):
    cat_id = int(callback.data.split(":")[2])
    await show_brands_page(callback, session, cat_id, page=1)
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:brandpage:"))
@owner_only
async def warehouse_brands_page(callback: CallbackQuery, session: AsyncSession):
    parts = callback.data.split(":")
    cat_id = int(parts[2])
    page = int(parts[3])
    await show_brands_page(callback, session, cat_id, page)


async def show_brands_page(callback: CallbackQuery, session: AsyncSession, cat_id: int, page: int) -> None:
    page_size = 8
    repo = CatalogRepo(session)

    category = await session.get(Category, cat_id)
    total_count = await repo.count_brands_by_category(cat_id)
    if not category or total_count == 0:
        await callback.answer("В этой категории нет брендов с товарами.", show_alert=True)
        return

    brands = await repo.get_brands_by_category_paginated(cat_id, page, page_size)

    kb = InlineKeyboardBuilder()
    for brand in brands:
        stats = await repo.get_brand_stats(brand.id, cat_id)
        btn_text = (
            f"🏷 {brand.name}\n"
            f"  {stats['product_count']} товаров | "
            f"{stats['total_items']} шт | "
            f"{stats['total_investment']:,.0f}₽"
        )
        kb.button(text=btn_text, callback_data=f"wh:brand:{cat_id}:{brand.id}")

    total_pages = (total_count + page_size - 1) // page_size
    nav_count = 0
    if page > 1:
        kb.button(text="⬅️", callback_data=f"wh:brandpage:{cat_id}:{page - 1}")
        nav_count += 1
    kb.button(text=f"{page}/{total_pages}", callback_data="ignore")
    nav_count += 1
    if page < total_pages:
        kb.button(text="➡️", callback_data=f"wh:brandpage:{cat_id}:{page + 1}")
        nav_count += 1

    kb.button(text="↩️ Назад", callback_data="wh:back_to_dash")
    layout = [1] * max(1, len(brands))
    layout.append(max(1, nav_count))
    layout.append(1)
    kb.adjust(*layout)

    text = f"📂 Категория: <b>{category.name}</b>\nВыберите бренд:"

    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@warehouse_router.callback_query(F.data.startswith("wh:brand:"))
@owner_only
async def warehouse_show_products(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    parts = callback.data.split(":")
    cat_id = int(parts[2])
    brand_id = int(parts[3])

    await state.update_data(current_cat_id=cat_id, current_brand_id=brand_id, current_sort="name")
    await show_products_list(callback, session, cat_id, brand_id, "name")


async def show_products_list(callback: CallbackQuery, session: AsyncSession, cat_id: int, brand_id: int, sort_by: str):
    repo = CatalogRepo(session)
    products = await repo.get_products_sorted(cat_id, brand_id, sort_by)
    brand = await session.get(Brand, brand_id)

    if not products:
        await callback.answer("Товаров не найдено", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    for product in products:
        total_qty = sum(stock.quantity for stock in product.stock)
        if total_qty == 0:
            status = "⚪️"
        elif total_qty <= 5:
            status = "🔴"
        elif total_qty <= 20:
            status = "🟡"
        else:
            status = "🟢"
        kb.button(text=f"{status} {product.title} ({total_qty} шт)", callback_data=f"wh:prod:{product.id}")

    sort_names = {"name": "По названию", "price": "По цене", "margin": "По марже", "stock": "По остаткам"}
    kb.button(text=f"↕️ Сортировка: {sort_names.get(sort_by, sort_by)}", callback_data="wh:sort_menu")
    kb.button(text="↩️ Назад", callback_data=f"wh:cat:{cat_id}")
    kb.adjust(1, 1, 1)

    text = f"🏷 Бренд: <b>{brand.name}</b>\nВыберите товар (сортировка: {sort_names.get(sort_by, sort_by)}):"

    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@warehouse_router.callback_query(F.data == "wh:sort_menu")
@owner_only
async def show_sort_menu(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 По названию", callback_data="wh:sort:name")
    kb.button(text="💰 По цене", callback_data="wh:sort:price")
    kb.button(text="📈 По марже", callback_data="wh:sort:margin")
    kb.button(text="📦 По остаткам", callback_data="wh:sort:stock")
    kb.button(text="↩️ Отмена", callback_data="wh:sort_cancel")
    kb.adjust(2, 2, 1)

    text = "↕️ <b>Выберите способ сортировки:</b>"
    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:sort:"))
@owner_only
async def apply_sort(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    sort_type = callback.data.split(":")[2]
    data = await state.get_data()

    await state.update_data(current_sort=sort_type)
    await show_products_list(callback, session, data["current_cat_id"], data["current_brand_id"], sort_type)
    await callback.answer()


@warehouse_router.callback_query(F.data == "wh:sort_cancel")
@owner_only
async def cancel_sort(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    sort_by = data.get("current_sort", "name")
    await show_products_list(callback, session, data["current_cat_id"], data["current_brand_id"], sort_by)
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:prod:"))
async def warehouse_product_card(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if isinstance(callback, CallbackQuery):
        if not await ensure_owner(callback, session):
            return

    if isinstance(callback, Message):
        product_id = (await state.get_data()).get("product_id")
        message = callback
    else:
        product_id, opened_from_procurement, procurement_qty = _parse_warehouse_product_callback(callback.data)
        await state.update_data(product_id=product_id)
        if opened_from_procurement:
            await state.update_data(warehouse_back_mode="proc", procurement_qty=procurement_qty)
        else:
            await state.update_data(warehouse_back_mode="brand", procurement_qty=None)
        message = callback.message

    repo = CatalogRepo(session)
    product = await repo.get_product_with_details(product_id)

    if not product:
        if isinstance(callback, CallbackQuery):
            await callback.answer("Товар не найден")
        return

    total_qty = sum(stock.quantity for stock in product.stock)
    sizes_str = ", ".join([f"{stock.size} ({stock.quantity})" for stock in product.stock if stock.quantity > 0]) or "Нет"
    margin = float(product.sale_price) - float(product.purchase_price)

    sold_stmt = (
        select(OrderItem.size, func.coalesce(func.sum(OrderItem.quantity), 0).label("sold_qty"))
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            OrderItem.product_id == product.id,
            Order.status == OrderStatus.COMPLETED.value,
        )
        .group_by(OrderItem.size)
        .order_by(func.sum(OrderItem.quantity).desc(), OrderItem.size.asc())
    )
    sold_rows = (await session.execute(sold_stmt)).all()
    sold_total = int(sum(int(row.sold_qty or 0) for row in sold_rows))
    sold_sizes_str = ", ".join([f"{row.size} ({int(row.sold_qty or 0)})" for row in sold_rows]) if sold_rows else "Нет продаж"

    if total_qty == 0:
        stock_status = "⚪️ Нет в наличии"
    elif total_qty <= 5:
        stock_status = f"🔴 Критический ({total_qty} шт)"
    elif total_qty <= 20:
        stock_status = f"🟡 Низкий ({total_qty} шт)"
    else:
        stock_status = f"🟢 Хороший ({total_qty} шт)"

    description = product.description or "Пусто"
    if len(description) > 100:
        description = description[:97] + "..."

    now = datetime.utcnow()
    days_ago = (now - product.created_at).days
    date_str = f"{days_ago}д назад" if days_ago > 0 else "Сегодня"
    state_data = await state.get_data()
    procurement_line = ""
    if state_data.get("warehouse_back_mode") == "proc":
        qty = state_data.get("procurement_qty")
        if isinstance(qty, int) and qty >= 0:
            procurement_line = f"📥 Закуплено за период: <b>{qty} шт</b>\n"

    text = (
        f"🛠 <b>УПРАВЛЕНИЕ ТОВАРОМ #{product.id}</b>\n\n"
        f"🏷 <b>{product.title}</b>\n"
        f"🏷️ Бренд: {product.brand.name if product.brand else 'Бренд не указан'}\n"
        f"🔖 SKU: <code>{product.sku}</code>\n"
        f"📅 Добавлен: {date_str}\n"
        f"{procurement_line}\n"
        f"<b>📊 ОСТАТКИ</b>\n"
        f"Статус: {stock_status}\n"
        f"Размеры: {sizes_str}\n"
        f"Продано: <b>{sold_total} шт</b>\n"
        f"Продажи по размерам: {sold_sizes_str}\n\n"
        f"<b>💰 ФИНАНСЫ</b>\n"
        f"Цена продажи: <b>{product.sale_price:g}₽</b>\n"
        f"Цена закупки: <b>{product.purchase_price:g}₽</b>\n"
        f"Маржа за ед.: <b>+{margin:g}₽</b>\n"
        f"Маржа всего: <b>+{margin * total_qty:,.0f}₽</b>\n\n"
        f"<b>📝 Описание</b>\n{description}"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Изм. Цену", callback_data="edit:price")
    kb.button(text="🏷 Изм. Бренд", callback_data="edit:brand")
    kb.button(text="📦 Изм. Остаток", callback_data="edit:stock")
    kb.button(text="📝 Изм. Описание", callback_data="edit:desc")
    kb.button(text="🔄 Обновить остатки", callback_data="stock:refresh")
    data = await state.get_data()
    if data.get("warehouse_back_mode") == "proc":
        kb.button(text="↩️ Назад", callback_data="wh:proc:return")
    else:
        kb.button(text="↩️ Назад", callback_data=f"wh:brand:{product.category_id}:{product.brand_id}")
    kb.adjust(2, 2, 1, 1)

    if product.photos:
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer_photo(product.photos[0].file_id, caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        if message.photo:
            await message.delete()
            await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        else:
            await message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@warehouse_router.callback_query(F.data == "edit:price")
@owner_only
async def edit_price_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductStates.edit_price)
    kb = InlineKeyboardBuilder()
    kb.button(text="↩️ Назад", callback_data="wh:prod_back")
    kb.button(text="↩️ Отмена", callback_data="owner:cancel")
    kb.adjust(2)
    await callback.message.answer(
        "Введите новые цены через пробел:\nFormat: <code>ЗАКУПКА ПРОДАЖА</code>\nПример: <code>25000 45000</code>",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@warehouse_router.callback_query(F.data == "edit:brand")
@owner_only
async def edit_brand_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductStates.edit_brand)
    kb = InlineKeyboardBuilder()
    kb.button(text="↩️ Назад", callback_data="wh:prod_back")
    kb.button(text="↩️ Отмена", callback_data="owner:cancel")
    kb.adjust(2)
    await callback.message.answer(
        "Введите новое имя бренда (например: <code>Zilli</code>)",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@warehouse_router.callback_query(F.data == "wh:prod_back")
@owner_only
async def edit_price_back(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await callback.answer()
    await warehouse_product_card(callback.message, session, state)


@warehouse_router.message(EditProductStates.edit_price)
@owner_only
async def edit_price_process(message: Message, state: FSMContext, session: AsyncSession):
    text = (message.text or "").strip()
    if text in _EXIT_TEXTS:
        await state.set_state(None)
        await show_owner_main_menu(message)
        return

    try:
        parts = text.split()
        new_purchase = float(parts[0])
        new_sale = float(parts[1])

        data = await state.get_data()
        repo = CatalogRepo(session)
        await repo.update_product_prices(data["product_id"], new_purchase, new_sale)
        await session.commit()

        await state.set_state(None)
        await message.answer("✅ Цены обновлены.")
        await warehouse_product_card(message, session, state)
    except Exception:
        kb = InlineKeyboardBuilder()
        kb.button(text="↩️ Назад", callback_data="wh:prod_back")
        kb.button(text="↩️ Отмена", callback_data="owner:cancel")
        kb.adjust(2)
        await message.answer(
            "⚠️ Ошибка. Введите два числа через пробел (ЗАКУП ПРОДАЖА).",
            reply_markup=kb.as_markup(),
        )


@warehouse_router.message(EditProductStates.edit_brand)
@owner_only
async def edit_brand_process(message: Message, state: FSMContext, session: AsyncSession):
    brand_name = (message.text or "").strip()
    if brand_name in _EXIT_TEXTS:
        await state.set_state(None)
        await show_owner_main_menu(message)
        return

    if not brand_name:
        await message.answer("⚠️ Название бренда не может быть пустым. Попробуйте ещё раз.")
        return

    data = await state.get_data()
    repo = CatalogRepo(session)
    updated = await repo.update_product_brand(data["product_id"], brand_name)
    if not updated:
        await message.answer("⚠️ Не удалось обновить бренд. Проверьте название и попробуйте снова.")
        return

    await session.commit()
    await state.set_state(None)
    await message.answer("✅ Бренд обновлён.")
    await warehouse_product_card(message, session, state)


@warehouse_router.callback_query(F.data == "edit:stock")
@owner_only
async def edit_stock_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    repo = CatalogRepo(session)
    product = await repo.get_product_with_details(data["product_id"])

    kb = InlineKeyboardBuilder()
    for stock in product.stock:
        kb.button(text=f"{stock.size} (сейчас: {stock.quantity})", callback_data=f"stock:size:{stock.size}")
    kb.button(text="➕ Добавить новый размер", callback_data="stock:new")
    kb.button(text="↩️ Отмена", callback_data="owner:cancel")
    kb.adjust(1)

    await callback.message.answer("Какой размер редактируем?", reply_markup=kb.as_markup())
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("stock:size:"))
@owner_only
async def edit_stock_choice(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("⚠️ Неверный формат данных", show_alert=True)
        return
    size = parts[-1]
    await state.update_data(editing_size=size)
    await state.set_state(EditProductStates.edit_stock_qty)
    await callback.message.answer(f"Введите новое количество для размера {size}:")


@warehouse_router.callback_query(F.data == "stock:new")
@owner_only
async def edit_stock_new(callback: CallbackQuery, state: FSMContext):
    await state.update_data(editing_size=None)
    await state.set_state(EditProductStates.edit_stock_qty)
    await callback.message.answer("Введите: РАЗМЕР КОЛИЧЕСТВО (Пример: <code>44 5</code>)", parse_mode="HTML")


@warehouse_router.message(EditProductStates.edit_stock_qty)
@owner_only
async def edit_stock_process(message: Message, state: FSMContext, session: AsyncSession):
    text = (message.text or "").strip()
    if text in _EXIT_TEXTS:
        await state.set_state(None)
        await show_owner_main_menu(message)
        return

    data = await state.get_data()
    product_id = data["product_id"]
    repo = CatalogRepo(session)

    try:
        if data.get("editing_size"):
            qty = int(text)
            await repo.update_stock_quantity(product_id, data["editing_size"], qty)
        else:
            parts = text.split()
            size, qty = parts[0], int(parts[1])
            await repo.update_stock_quantity(product_id, size, qty)

        await session.commit()
        await state.set_state(None)
        await message.answer("✅ Остатки обновлены.")
        await warehouse_product_card(message, session, state)
    except Exception:
        await message.answer("⚠️ Ошибка формата. Попробуйте еще раз.")


@warehouse_router.callback_query(F.data == "stock:refresh")
@owner_only
async def stock_refresh(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await callback.answer("Обновляю остатки…")
    await warehouse_product_card(callback.message, session, state)


@warehouse_router.callback_query(F.data == "edit:desc")
@owner_only
async def edit_desc_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductStates.edit_description)
    await callback.message.answer("Введите новое описание (или '-' чтобы удалить):")
    await callback.answer()


@warehouse_router.message(EditProductStates.edit_description)
@owner_only
async def edit_desc_process(message: Message, state: FSMContext, session: AsyncSession):
    raw_text = (message.text or "").strip()
    if raw_text in _EXIT_TEXTS:
        await state.set_state(None)
        await show_owner_main_menu(message)
        return

    desc = raw_text
    if desc == "-":
        desc = None

    data = await state.get_data()
    repo = CatalogRepo(session)
    await repo.update_product_description(data["product_id"], desc)
    await session.commit()

    await state.set_state(None)
    await message.answer("✅ Описание обновлено.")
    await warehouse_product_card(message, session, state)
