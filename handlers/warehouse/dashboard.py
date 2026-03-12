from __future__ import annotations

from aiogram import F
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from database.catalog_repo import CatalogRepo
from utils.tenants import get_runtime_tenant
from ..owner_utils import owner_only
from .common import warehouse_router


async def _get_catalog_repo(session: AsyncSession) -> CatalogRepo:
    tenant = await get_runtime_tenant(session)
    return CatalogRepo(session, tenant_id=tenant.id)


@warehouse_router.message(F.text == "📊 Склад")
@owner_only
async def warehouse_dashboard(message: Message, session: AsyncSession):
    await send_warehouse_dashboard(message, session)


async def send_warehouse_dashboard(message: Message, session: AsyncSession) -> None:
    repo = await _get_catalog_repo(session)
    products = await repo.get_all_products_with_stock()

    if not products:
        await message.answer("📭 Склад пуст. Добавьте товары через меню «📦 Товары».")
        return

    total_items = 0
    total_purchase_sum = 0.0
    total_sale_sum = 0.0

    for product in products:
        qty = sum(stock.quantity for stock in product.stock)
        total_items += qty
        total_purchase_sum += float(product.purchase_price) * qty
        total_sale_sum += float(product.sale_price) * qty

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
    kb.button(text="🚨 Критические остатки", callback_data="wh:filter:critical")
    kb.button(text="📈 Топ по марже", callback_data="wh:filter:margin")
    kb.button(text="⚪️ Нулевой остаток", callback_data="wh:filter:zero")
    kb.button(text="📦 Закупка", callback_data="wh:proc:start")
    kb.button(text="📥 Скачать отчет", callback_data="wh:report:start")
    kb.button(text="📂 По категориям", callback_data="wh:filter:categories")
    kb.button(text="🧭 В меню", callback_data="owner:cancel")
    kb.adjust(2, 2, 2, 1)

    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@warehouse_router.callback_query(F.data == "wh:filter:critical")
@owner_only
async def filter_critical_stock(callback: CallbackQuery, session: AsyncSession):
    repo = await _get_catalog_repo(session)
    products = await repo.get_critical_stock_products(limit=15)

    if not products:
        await callback.answer("✅ Критических остатков не найдено!", show_alert=True)
        return

    text = "🚨 <b>ТОВАРЫ С КРИТИЧЕСКИМ ОСТАТКОМ (≤5 шт)</b>\n\n"
    kb = InlineKeyboardBuilder()
    for product in products:
        qty = sum(stock.quantity for stock in product.stock)
        kb.button(text=f"{product.title} ({qty}⚠️)", callback_data=f"wh:prod:{product.id}")
    kb.button(text="↩️ Назад", callback_data="wh:back_to_dash")
    kb.adjust(1)

    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@warehouse_router.callback_query(F.data == "wh:filter:margin")
@owner_only
async def filter_top_margin(callback: CallbackQuery, session: AsyncSession):
    repo = await _get_catalog_repo(session)
    products = await repo.get_top_margin_products(limit=5)

    if not products:
        await callback.answer("Товаров не найдено", show_alert=True)
        return

    text = "📈 <b>ТОП-5 ТОВАРОВ ПО МАРЖЕ</b>\n\n"
    kb = InlineKeyboardBuilder()
    for product in products:
        margin = float(product.sale_price) - float(product.purchase_price)
        kb.button(text=f"{product.title} (+{margin:g}₽)", callback_data=f"wh:prod:{product.id}")
    kb.button(text="↩️ Назад", callback_data="wh:back_to_dash")
    kb.adjust(1)

    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@warehouse_router.callback_query(F.data == "wh:filter:zero")
@owner_only
async def filter_zero_stock(callback: CallbackQuery, session: AsyncSession):
    repo = await _get_catalog_repo(session)
    products = await repo.get_zero_stock_products(limit=15)

    if not products:
        await callback.answer("✅ Нет товаров с нулевым остатком!", show_alert=True)
        return

    text = "⚪️ <b>ТОВАРЫ БЕЗ ОСТАТКОВ</b>\n\n"
    kb = InlineKeyboardBuilder()
    for product in products:
        kb.button(text=product.title, callback_data=f"wh:prod:{product.id}")
    kb.button(text="↩️ Назад", callback_data="wh:back_to_dash")
    kb.adjust(1)

    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@warehouse_router.callback_query(F.data == "wh:filter:categories")
@owner_only
async def filter_by_categories(callback: CallbackQuery, session: AsyncSession):
    repo = await _get_catalog_repo(session)
    categories = await repo.list_categories()

    text = "📂 <b>КАТЕГОРИИ</b>\n\n"
    kb = InlineKeyboardBuilder()
    for category in categories:
        stats = await repo.get_category_stats(category.id)
        text_btn = f"📂 {category.name} ({stats['product_count']} товаров, {stats['total_items']} шт)"
        kb.button(text=text_btn, callback_data=f"wh:cat:{category.id}")
    kb.button(text="↩️ Назад", callback_data="wh:back_to_dash")
    kb.adjust(1)

    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@warehouse_router.callback_query(F.data == "wh:back_to_dash")
@owner_only
async def back_to_dashboard(callback: CallbackQuery, session: AsyncSession):
    await callback.message.delete()
    await send_warehouse_dashboard(callback.message, session)
