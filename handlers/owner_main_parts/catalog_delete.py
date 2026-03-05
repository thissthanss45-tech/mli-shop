from __future__ import annotations

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from database.catalog_repo import CatalogRepo
from models.catalog import Product
from ..owner_states import DeleteProductStates, DeleteCategoryStates, DeleteBrandStates
from ..owner_keyboards import build_categories_kb, build_brands_kb
from ..owner_utils import owner_only, show_owner_main_menu
from .common import main_router


@main_router.message(F.text == "🗑 Удалить товар")
@owner_only
async def owner_delete_product_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
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
    kb.button(text="↩️ Назад", callback_data="owner:cancel")
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
    kb.button(text="↩️ Назад", callback_data="owner:cancel")
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


@main_router.message(F.text == "🗑 Удалить категорию")
@owner_only
async def owner_delete_category_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    repo = CatalogRepo(session)
    categories = await repo.list_categories()
    if not categories:
        await message.answer("Нет категорий.")
        return
    kb = InlineKeyboardBuilder()
    for cat in categories:
        kb.button(text=cat.name, callback_data=f"owner:delcat:{cat.id}")
    kb.button(text="↩️ Назад", callback_data="owner:cancel")
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
    kb.button(text="↩️ Назад", callback_data="owner:cancel")
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


@main_router.message(F.text == "🗑 Удалить бренд")
@owner_only
async def owner_delete_brand_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    repo = CatalogRepo(session)
    brands = await repo.list_brands()
    if not brands:
        await message.answer("Нет брендов.")
        return
    kb = InlineKeyboardBuilder()
    for brand in brands:
        kb.button(text=brand.name, callback_data=f"owner:delbrand:{brand.id}")
    kb.button(text="↩️ Назад", callback_data="owner:cancel")
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
    kb.button(text="↩️ Назад", callback_data="owner:cancel")
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
