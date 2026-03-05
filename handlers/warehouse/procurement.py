from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import datetime

from aiogram import F
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Product, Category, Brand, StockMovement, MovementDirection, MovementOperation
from ..owner_states import WarehouseYearStates
from ..owner_utils import owner_only
from .common import (
    MIN_PROCUREMENT_YEAR,
    MAX_SELECT_YEAR,
    YEAR_PAGE_SIZE,
    warehouse_router,
    safe_callback_edit_text,
)


def _normalize_proc_year_page_start(start_year: int) -> int:
    upper_start = max(MIN_PROCUREMENT_YEAR, MAX_SELECT_YEAR - YEAR_PAGE_SIZE + 1)
    return max(MIN_PROCUREMENT_YEAR, min(start_year, upper_start))


def _procurement_years_kb(start_year: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    start_year = _normalize_proc_year_page_start(start_year)
    years = [year for year in range(start_year, start_year + YEAR_PAGE_SIZE) if MIN_PROCUREMENT_YEAR <= year <= MAX_SELECT_YEAR]
    for year in years:
        kb.button(text=str(year), callback_data=f"wh:proc:y:{year}")

    prev_start = _normalize_proc_year_page_start(start_year - YEAR_PAGE_SIZE)
    next_start = _normalize_proc_year_page_start(start_year + YEAR_PAGE_SIZE)
    kb.button(text="⬅️", callback_data=f"wh:proc:years:{prev_start}")
    kb.button(text="➡️", callback_data=f"wh:proc:years:{next_start}")

    kb.button(text="✍️ Ввести год", callback_data="wh:proc:year_input")
    kb.button(text="↩️ Назад", callback_data="wh:back_to_dash")
    kb.adjust(3, 3, 2, 1, 1)
    return kb


def _procurement_months_kb(year: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    month_labels = [
        "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
        "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
    ]
    for month in range(1, 13):
        kb.button(text=month_labels[month - 1], callback_data=f"wh:proc:m:{year}:{month}")
    kb.button(text="↩️ К годам", callback_data=f"wh:proc:years:{_normalize_proc_year_page_start(year - 2)}")
    kb.button(text="↩️ Назад", callback_data="wh:back_to_dash")
    kb.adjust(4, 4, 4, 2)
    return kb


def _procurement_days_kb(year: int, month: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    days_in_month = calendar.monthrange(year, month)[1]
    for day in range(1, days_in_month + 1):
        kb.button(text=str(day), callback_data=f"wh:proc:d:{year}:{month}:{day}")

    kb.button(text="📦 Весь месяц", callback_data=f"wh:proc:month:{year}:{month}")
    kb.button(text="↩️ К месяцам", callback_data=f"wh:proc:y:{year}")
    kb.button(text="↩️ Назад", callback_data="wh:back_to_dash")
    kb.adjust(7, 7, 7, 7, 7, 7, 7, 3)
    return kb


def _build_procurement_product_callback(product_id: int, purchased_qty: int) -> str:
    return f"wh:prod:{product_id}:proc:{purchased_qty}"


async def _show_procurement_page(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    page: int,
) -> None:
    data = await state.get_data()
    start_iso = data.get("proc_start")
    end_iso = data.get("proc_end")
    period_label = data.get("proc_label", "период")
    if not start_iso or not end_iso:
        await callback.answer("Период не выбран", show_alert=True)
        return

    start_dt = datetime.fromisoformat(start_iso)
    end_dt = datetime.fromisoformat(end_iso)

    page_size = 8
    selected_cat_id = data.get("proc_cat_id")
    selected_brand_id = data.get("proc_brand_id")

    base_conditions = [
        StockMovement.created_at.between(start_dt, end_dt),
        StockMovement.direction == MovementDirection.IN.value,
        StockMovement.operation_type == MovementOperation.MANUAL_ADD.value,
    ]

    product_filters = []
    if selected_cat_id:
        product_filters.append(Product.category_id == int(selected_cat_id))
    if selected_brand_id:
        product_filters.append(Product.brand_id == int(selected_brand_id))

    count_stmt = (
        select(func.count(func.distinct(StockMovement.product_id)))
        .select_from(StockMovement)
        .join(Product, Product.id == StockMovement.product_id)
        .where(*base_conditions, *product_filters)
    )
    total_count = int((await session.execute(count_stmt)).scalar() or 0)
    if total_count == 0:
        await callback.answer("Закупок за период не найдено", show_alert=True)
        return

    total_pages = max(1, (total_count + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * page_size

    grouped_stmt = (
        select(
            StockMovement.product_id,
            func.sum(StockMovement.quantity).label("purchased_qty"),
            func.max(StockMovement.created_at).label("last_procured_at"),
        )
        .select_from(StockMovement)
        .join(Product, Product.id == StockMovement.product_id)
        .where(*base_conditions, *product_filters)
        .group_by(StockMovement.product_id)
        .order_by(func.max(StockMovement.created_at).desc(), StockMovement.product_id.desc())
        .limit(page_size)
        .offset(offset)
    )
    grouped_rows = (await session.execute(grouped_stmt)).all()
    product_ids = [int(row.product_id) for row in grouped_rows]

    products_map: dict[int, Product] = {}
    if product_ids:
        products_stmt = (
            select(Product)
            .options(selectinload(Product.stock), selectinload(Product.brand))
            .where(Product.id.in_(product_ids))
        )
        products = (await session.execute(products_stmt)).scalars().all()
        products_map = {int(product.id): product for product in products}

    await state.update_data(proc_page=page)

    brand_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"qty": 0, "products": 0})
    for row in grouped_rows:
        product = products_map.get(int(row.product_id))
        if not product:
            continue
        brand_name = product.brand.name if product.brand else "Без бренда"
        purchased_qty = int(row.purchased_qty or 0)
        brand_totals[brand_name]["qty"] += purchased_qty
        brand_totals[brand_name]["products"] += 1

    brands_text = "\n".join(
        f"• {brand}: {stats['qty']} шт ({stats['products']} тов.)"
        for brand, stats in sorted(brand_totals.items(), key=lambda item: item[0].lower())
    )

    scope_bits: list[str] = [period_label]
    if data.get("proc_cat_name"):
        scope_bits.append(f"Категория: {data['proc_cat_name']}")
    if data.get("proc_brand_name"):
        scope_bits.append(f"Бренд: {data['proc_brand_name']}")
    scope_label = " | ".join(scope_bits)

    text = (
        f"📦 <b>ЗАКУПКА ({scope_label})</b>\n"
        f"Страница {page}/{total_pages}\n\n"
        f"<b>🏷 По брендам:</b>\n{brands_text}\n\n"
    )
    kb = InlineKeyboardBuilder()
    for row in grouped_rows:
        product = products_map.get(int(row.product_id))
        if not product:
            continue
        brand_name = product.brand.name if product.brand else "Без бренда"
        purchased_qty = int(row.purchased_qty or 0)
        procured_at = row.last_procured_at
        date_lbl = procured_at.strftime("%d.%m.%Y") if procured_at else "-"
        kb.button(
            text=f"[{brand_name}] {product.title} (+{purchased_qty} шт, {date_lbl})",
            callback_data=_build_procurement_product_callback(product.id, purchased_qty),
        )

    nav_count = 0
    if page > 1:
        kb.button(text="⬅️", callback_data=f"wh:proc:page:{page - 1}")
        nav_count += 1
    kb.button(text=f"{page}/{total_pages}", callback_data="ignore")
    nav_count += 1
    if page < total_pages:
        kb.button(text="➡️", callback_data=f"wh:proc:page:{page + 1}")
        nav_count += 1

    kb.button(text="🏷 К брендам", callback_data="wh:proc:brands")
    kb.button(text="📂 К категориям", callback_data="wh:proc:cats")
    kb.button(text="📅 Выбрать другой период", callback_data="wh:proc:start")
    kb.button(text="↩️ Назад", callback_data="wh:back_to_dash")

    layout = [1] * max(1, len(grouped_rows))
    layout.append(max(1, nav_count))
    layout.append(1)
    layout.append(1)
    layout.append(1)
    kb.adjust(*layout)

    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


async def _show_procurement_categories(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    start_iso = data.get("proc_start")
    end_iso = data.get("proc_end")
    period_label = data.get("proc_label", "период")
    if not start_iso or not end_iso:
        await callback.answer("Период не выбран", show_alert=True)
        return

    start_dt = datetime.fromisoformat(start_iso)
    end_dt = datetime.fromisoformat(end_iso)

    base_conditions = [
        StockMovement.created_at.between(start_dt, end_dt),
        StockMovement.direction == MovementDirection.IN.value,
        StockMovement.operation_type == MovementOperation.MANUAL_ADD.value,
    ]

    stmt = (
        select(
            Category.id,
            Category.name,
            func.sum(StockMovement.quantity).label("qty"),
            func.count(func.distinct(Product.id)).label("products"),
        )
        .select_from(StockMovement)
        .join(Product, Product.id == StockMovement.product_id)
        .join(Category, Category.id == Product.category_id)
        .where(*base_conditions)
        .group_by(Category.id, Category.name)
        .order_by(Category.name.asc())
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        await callback.answer("Закупок за период не найдено", show_alert=True)
        return

    await state.update_data(proc_cat_id=None, proc_cat_name=None, proc_brand_id=None, proc_brand_name=None, proc_page=1)

    text = f"📦 <b>ЗАКУПКА ({period_label})</b>\nВыберите категорию:"
    kb = InlineKeyboardBuilder()
    for row in rows:
        qty = int(row.qty or 0)
        products = int(row.products or 0)
        kb.button(text=f"📂 {row.name} (+{qty} шт, {products} тов.)", callback_data=f"wh:proc:cat:{int(row.id)}")

    kb.button(text="📅 Выбрать другой период", callback_data="wh:proc:start")
    kb.button(text="↩️ Назад", callback_data="wh:back_to_dash")
    kb.adjust(1)

    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


async def _show_procurement_brands(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    start_iso = data.get("proc_start")
    end_iso = data.get("proc_end")
    period_label = data.get("proc_label", "период")
    cat_id = data.get("proc_cat_id")
    cat_name = data.get("proc_cat_name")
    if not start_iso or not end_iso or not cat_id:
        await callback.answer("Сначала выберите категорию", show_alert=True)
        return

    start_dt = datetime.fromisoformat(start_iso)
    end_dt = datetime.fromisoformat(end_iso)

    base_conditions = [
        StockMovement.created_at.between(start_dt, end_dt),
        StockMovement.direction == MovementDirection.IN.value,
        StockMovement.operation_type == MovementOperation.MANUAL_ADD.value,
        Product.category_id == int(cat_id),
    ]

    stmt = (
        select(
            Brand.id,
            Brand.name,
            func.sum(StockMovement.quantity).label("qty"),
            func.count(func.distinct(Product.id)).label("products"),
        )
        .select_from(StockMovement)
        .join(Product, Product.id == StockMovement.product_id)
        .join(Brand, Brand.id == Product.brand_id)
        .where(*base_conditions)
        .group_by(Brand.id, Brand.name)
        .order_by(Brand.name.asc())
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        await callback.answer("Для категории нет закупок в периоде", show_alert=True)
        return

    await state.update_data(proc_brand_id=None, proc_brand_name=None, proc_page=1)

    text = f"📦 <b>ЗАКУПКА ({period_label})</b>\n📂 Категория: <b>{cat_name}</b>\nВыберите бренд:"
    kb = InlineKeyboardBuilder()
    for row in rows:
        qty = int(row.qty or 0)
        products = int(row.products or 0)
        kb.button(text=f"🏷 {row.name} (+{qty} шт, {products} тов.)", callback_data=f"wh:proc:brand:{int(row.id)}")

    kb.button(text="↩️ К категориям", callback_data="wh:proc:cats")
    kb.button(text="📅 Выбрать другой период", callback_data="wh:proc:start")
    kb.adjust(1)

    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@warehouse_router.callback_query(F.data.in_({"wh:proc:start", "wh:filter:new"}))
@owner_only
async def procurement_start(callback: CallbackQuery, session: AsyncSession):
    now_year = datetime.now().year
    start_year = _normalize_proc_year_page_start(now_year - 2)
    await safe_callback_edit_text(
        callback,
        "📅 Выберите год закупки:",
        reply_markup=_procurement_years_kb(start_year).as_markup(),
    )
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:proc:years:"))
@owner_only
async def procurement_years_page(callback: CallbackQuery, session: AsyncSession):
    start_year = _normalize_proc_year_page_start(int(callback.data.split(":")[-1]))
    await safe_callback_edit_text(
        callback,
        "📅 Выберите год закупки:",
        reply_markup=_procurement_years_kb(start_year).as_markup(),
    )
    await callback.answer()


@warehouse_router.callback_query(F.data == "wh:proc:year_input")
@owner_only
async def procurement_year_input_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    await state.set_state(WarehouseYearStates.waiting_for_procurement_year)
    await callback.message.answer("✍️ Введите год для закупки (например, 2027):")
    await callback.answer()


@warehouse_router.message(WarehouseYearStates.waiting_for_procurement_year)
@owner_only
async def procurement_year_input_finish(message: Message, state: FSMContext, session: AsyncSession):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Введите год цифрами, например 2027.")
        return
    year = int(text)
    if year < MIN_PROCUREMENT_YEAR or year > MAX_SELECT_YEAR:
        await message.answer(f"Год должен быть в диапазоне {MIN_PROCUREMENT_YEAR}..{MAX_SELECT_YEAR}.")
        return
    await state.clear()
    await message.answer(
        f"📆 Выберите месяц закупки ({year}):",
        reply_markup=_procurement_months_kb(year).as_markup(),
    )


@warehouse_router.callback_query(F.data.startswith("wh:proc:y:"))
@owner_only
async def procurement_choose_month(callback: CallbackQuery, session: AsyncSession):
    year = int(callback.data.split(":")[-1])
    await safe_callback_edit_text(
        callback,
        f"📆 Выберите месяц закупки ({year}):",
        reply_markup=_procurement_months_kb(year).as_markup(),
    )
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:proc:m:"))
@owner_only
async def procurement_choose_day(callback: CallbackQuery, session: AsyncSession):
    _, _, _, year_raw, month_raw = callback.data.split(":")
    year = int(year_raw)
    month = int(month_raw)
    await safe_callback_edit_text(
        callback,
        f"🗓 Выберите день ({month:02d}.{year}) или «Весь месяц»:",
        reply_markup=_procurement_days_kb(year, month).as_markup(),
    )
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:proc:d:"))
@owner_only
async def procurement_day(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    _, _, _, y, m, d = callback.data.split(":")
    start_dt = datetime(int(y), int(m), int(d), 0, 0, 0)
    end_dt = datetime(int(y), int(m), int(d), 23, 59, 59, 999999)
    await state.update_data(
        proc_start=start_dt.isoformat(),
        proc_end=end_dt.isoformat(),
        proc_label=start_dt.strftime("%d.%m.%Y"),
        proc_cat_id=None,
        proc_cat_name=None,
        proc_brand_id=None,
        proc_brand_name=None,
        proc_page=1,
    )
    await _show_procurement_categories(callback, session, state)
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:proc:month:"))
@owner_only
async def procurement_month(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    _, _, _, y, m = callback.data.split(":")
    year = int(y)
    month = int(m)
    days = calendar.monthrange(year, month)[1]
    start_dt = datetime(year, month, 1, 0, 0, 0)
    end_dt = datetime(year, month, days, 23, 59, 59, 999999)
    await state.update_data(
        proc_start=start_dt.isoformat(),
        proc_end=end_dt.isoformat(),
        proc_label=f"{month:02d}.{year}",
        proc_cat_id=None,
        proc_cat_name=None,
        proc_brand_id=None,
        proc_brand_name=None,
        proc_page=1,
    )
    await _show_procurement_categories(callback, session, state)
    await callback.answer()


@warehouse_router.callback_query(F.data == "wh:proc:cats")
@owner_only
async def procurement_categories(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    await _show_procurement_categories(callback, session, state)
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:proc:cat:"))
@owner_only
async def procurement_select_category(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    cat_id = int(callback.data.split(":")[-1])
    category = await session.get(Category, cat_id)
    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    await state.update_data(proc_cat_id=cat_id, proc_cat_name=category.name, proc_brand_id=None, proc_brand_name=None, proc_page=1)
    await _show_procurement_brands(callback, session, state)
    await callback.answer()


@warehouse_router.callback_query(F.data == "wh:proc:brands")
@owner_only
async def procurement_brands(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    await _show_procurement_brands(callback, session, state)
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:proc:brand:"))
@owner_only
async def procurement_select_brand(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    brand_id = int(callback.data.split(":")[-1])
    brand = await session.get(Brand, brand_id)
    if not brand:
        await callback.answer("Бренд не найден", show_alert=True)
        return
    await state.update_data(proc_brand_id=brand_id, proc_brand_name=brand.name, proc_page=1)
    await _show_procurement_page(callback, session, state, page=1)
    await callback.answer()


@warehouse_router.callback_query(F.data.startswith("wh:proc:page:"))
@owner_only
async def procurement_page(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    page = int(callback.data.split(":")[-1])
    await _show_procurement_page(callback, session, state, page=page)
    await callback.answer()


@warehouse_router.callback_query(F.data == "wh:proc:return")
@owner_only
async def procurement_return_from_product(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    page = int(data.get("proc_page") or 1)
    await _show_procurement_page(callback, session, state, page=page)
    await callback.answer()
