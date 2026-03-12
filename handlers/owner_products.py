"""Хэндлеры добавления и редактирования товара для владельца."""

import asyncio
from typing import Any, Dict, List
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder 

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.catalog_repo import CatalogRepo
from models.catalog import Category, Brand, Product
from models.users import User, UserRole
from utils.product_media import build_product_media_group, describe_media_item, normalize_media_type
from utils.tenants import get_runtime_tenant, get_runtime_tenant_role_for_tg_id, list_tenant_recipient_ids

from .owner_states import (
    AddProductStates,
    AddCategoryBrandStates,
    EditProductStates,
)
from .owner_keyboards import (
    cancel_kb,
    yes_no_cancel_kb,
    done_cancel_kb,
    build_categories_kb,
    build_brands_kb,
    owner_products_menu_kb,
)
from .owner_utils import ensure_owner, owner_only, show_owner_main_menu

product_router = Router(name="owner_products")

FORBIDDEN_ENTITY_NAMES = {
    "✏️ Редактировать товар",
    "🗑 Удалить товар",
    "➕ Добавить товар",
    "🗑 Удалить категорию",
    "🗑 Удалить бренд",
}


def _normalize_text(text: str | None) -> str:
    return (text or "").strip()


def _is_cancel_or_back_text(text: str | None) -> bool:
    value = _normalize_text(text)
    return value in {
        "⬅ Назад",
        "🔙 Назад",
        "↩️ Назад",
        "🔙 Отмена",
        "⛔ Отмена",
        "↩️ Отмена",
        "Отмена",
    }


async def _show_products_menu(message: Message) -> None:
    kb = owner_products_menu_kb()
    await message.answer(
        "📦 Управление товарами:\n\nВыбери действие:",
        reply_markup=kb,
    )


async def _maybe_show_staff_menu(message: Message, session: AsyncSession) -> bool:
    role = await get_runtime_tenant_role_for_tg_id(session, message.from_user.id)
    if role == UserRole.STAFF.value:
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🛍 Каталог"), KeyboardButton(text="📋 Заказы")],
                [KeyboardButton(text="💳 Касса")],
            ],
            resize_keyboard=True,
        )
        await message.answer("✅ Готово.", reply_markup=kb)
        return True
    return False


def _is_staff_menu_text(text: str) -> bool:
    return text in {"🛍 Каталог", "📋 Заказы", "💳 Касса"}


async def _send_product_media_preview(
    message: Message,
    media_items: list[Any],
    caption: str,
    reply_markup: Any | None = None,
) -> None:
    if not media_items:
        await message.answer(caption, reply_markup=reply_markup, parse_mode="HTML")
        return

    if len(media_items) > 1:
        album = build_product_media_group(media_items, caption)
        await message.answer_media_group(media=album.build())
        if reply_markup is not None:
            await message.answer("👇 Действия:", reply_markup=reply_markup)
        return

    media = media_items[0]
    if normalize_media_type(getattr(media, "media_type", None)) == "video":
        await message.answer_video(media.file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await message.answer_photo(media.file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")


async def _get_catalog_repo(session: AsyncSession) -> CatalogRepo:
    tenant = await get_runtime_tenant(session)
    return CatalogRepo(session, tenant_id=tenant.id)


# ==========================================
#          ГЛАВНОЕ МЕНЮ ТОВАРОВ
# ==========================================

@product_router.message(F.text == "📦 Товары")
@owner_only
async def owner_menu_products(
    message: Message,
    state: FSMContext,
    session: AsyncSession | None = None,
) -> None:
    """Меню управления товарами."""
    await _show_products_menu(message)


# ==========================================
#          ДОБАВЛЕНИЕ КАТЕГОРИИ
# ==========================================

@product_router.message(F.text == "➕ Добавить категорию")
@owner_only
async def owner_add_category_start(
    message: Message,
    state: FSMContext,
    session: AsyncSession | None = None,
) -> None:
    """Начало добавления категории."""
    await state.set_state(AddCategoryBrandStates.enter_category_name)
    await message.answer(
        "Введи название категории (например: Одежда, Обувь):",
        reply_markup=cancel_kb(),
    )


@product_router.message(AddCategoryBrandStates.enter_category_name)
async def owner_add_category_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Сохранение названия категории."""
    name = (message.text or "").strip()

    # Обработка кнопок меню (если передумал)
    if _is_cancel_or_back_text(name):
        await state.clear()
        await owner_menu_products(message, state, session)
        return

    # Переключение на другие функции
    if name == "➕ Добавить бренд":
        await state.clear()
        await owner_add_brand_start(message, state, session)
        return
    if name == "➕ Добавить товар":
        await state.clear()
        await owner_menu_products(message, state, session)
        return

    # Защита от названий кнопок
    if name in FORBIDDEN_ENTITY_NAMES:
        await message.answer("⚠️ Нельзя называть категорию именем кнопки! Введи название текстом:")
        return

    if not name:
        await message.answer("Название категории не может быть пустым. Введи ещё раз:", reply_markup=cancel_kb())
        return

    repo = await _get_catalog_repo(session)
    await repo.get_or_create_category(name=name)
    await session.commit()

    await state.clear()
    await message.answer(f"✅ Категория «{name}» добавлена.")
    await owner_menu_products(message, state, session)


# ==========================================
#          ДОБАВЛЕНИЕ БРЕНДА
# ==========================================

@product_router.message(F.text == "➕ Добавить бренд")
@owner_only
async def owner_add_brand_start(
    message: Message,
    state: FSMContext,
    session: AsyncSession | None = None,
) -> None:
    """Начало добавления бренда."""
    # Переводим бота в состояние ожидания ввода названия бренда
    await state.set_state(AddCategoryBrandStates.enter_brand_name)
    await message.answer(
        "✍️ Введите название нового бренда (например: Zilli, Brioni):",
        reply_markup=cancel_kb(),
    )


@product_router.message(AddCategoryBrandStates.enter_brand_name)
async def owner_add_brand_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Сохранение названия бренда."""
    name = (message.text or "").strip()

    # Обработка кнопок меню
    if _is_cancel_or_back_text(name):
        await state.clear()
        await owner_menu_products(message, state, session)
        return

    # Переключение на другие функции
    if name == "➕ Добавить категорию":
        await state.clear()
        await owner_add_category_start(message, state, session)
        return
    if name == "➕ Добавить товар":
        await state.clear()
        await owner_menu_products(message, state, session)
        return

    # Защита от названий кнопок
    if name in FORBIDDEN_ENTITY_NAMES:
        await message.answer("⚠️ Нельзя называть бренд именем кнопки! Введи название текстом:")
        return

    if not name:
        await message.answer("Название бренда не может быть пустым. Введи ещё раз:", reply_markup=cancel_kb())
        return

    repo = await _get_catalog_repo(session)
    await repo.get_or_create_brand(name=name)
    await session.commit()

    await state.clear()
    await message.answer(f"✅ Бренд «{name}» добавлен.")
    await owner_menu_products(message, state, session)


# ==========================================
#          ДОБАВЛЕНИЕ ТОВАРА
# ==========================================

@product_router.message(F.text == "➕ Добавить товар")
@owner_only
async def owner_add_product_start(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Начало добавления товара."""
    repo = await _get_catalog_repo(session)
    categories = await repo.list_categories()

    if not categories:
        await message.answer("Категории пока не созданы. Сначала добавь категорию.")
        return

    await state.clear()
    await state.set_state(AddProductStates.choose_category)
    kb = build_categories_kb(list(categories))
    await message.answer("Выбери категорию товара:", reply_markup=kb)


@product_router.callback_query(AddProductStates.choose_category, F.data.startswith("owner:cat:"))
async def owner_choose_category(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    category_id = int(callback.data.split(":")[-1])
    await state.update_data(category_id=category_id)

    repo = await _get_catalog_repo(session)
    brands = await repo.list_brands()

    if not brands:
        await callback.message.edit_text("Бренды пока не созданы. Сначала добавь бренд.")
        await state.clear()
        await callback.answer()
        return

    kb = build_brands_kb(list(brands))
    await state.set_state(AddProductStates.choose_brand)
    await callback.message.edit_text("Выбери бренд товара:", reply_markup=kb)
    await callback.answer()


@product_router.callback_query(AddProductStates.choose_brand, F.data.startswith("owner:brand:"))
async def owner_choose_brand(callback: CallbackQuery, state: FSMContext) -> None:
    brand_id = int(callback.data.split(":")[-1])
    await state.update_data(brand_id=brand_id)
    await state.set_state(AddProductStates.enter_name)

    await callback.message.edit_text(
        "Введи название модели (например: Брюки Zilli классические):",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@product_router.message(AddProductStates.enter_name)
async def owner_enter_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    name = _normalize_text(message.text)
    if _is_cancel_or_back_text(name):
        await state.clear()
        await owner_menu_products(message, state, session)
        return

    if name in FORBIDDEN_ENTITY_NAMES:
        await message.answer("⚠️ Нельзя называть товар именем кнопки! Введи название текстом:")
        return

    if not name:
        await message.answer("Название не может быть пустым.", reply_markup=cancel_kb())
        return

    await state.update_data(name=name)
    await state.set_state(AddProductStates.enter_purchase_price)
    await message.answer("Введи закупочную цену (число):", reply_markup=cancel_kb())


@product_router.message(AddProductStates.enter_purchase_price)
async def owner_enter_purchase_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if _is_cancel_or_back_text(message.text):
        await state.clear()
        await owner_menu_products(message, state, session)
        return

    try:
        value = float(_normalize_text(message.text).replace(" ", "").replace(",", "."))
        if value < 0: raise ValueError
    except ValueError:
        await message.answer("Некорректное число. Введи закупочную цену ещё раз:", reply_markup=cancel_kb())
        return

    await state.update_data(purchase_price=value)
    await state.set_state(AddProductStates.enter_sale_price)
    await message.answer("Введи продажную цену (число):", reply_markup=cancel_kb())


@product_router.message(AddProductStates.enter_sale_price)
async def owner_enter_sale_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if _is_cancel_or_back_text(message.text):
        await state.clear()
        await owner_menu_products(message, state, session)
        return

    try:
        value = float(_normalize_text(message.text).replace(" ", "").replace(",", "."))
        if value < 0: raise ValueError
    except ValueError:
        await message.answer("Некорректное число. Введи продажную цену ещё раз:", reply_markup=cancel_kb())
        return

    await state.update_data(sale_price=value)
    await state.set_state(AddProductStates.ask_photos)
    await message.answer("Добавить фото товара? Можно до 10 фото.", reply_markup=yes_no_cancel_kb())


@product_router.callback_query(AddProductStates.ask_photos, F.data == "owner:photos:yes")
async def owner_photos_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(media=[])
    await state.set_state(AddProductStates.upload_photos)
    await callback.message.edit_text("Отправляй фото или видео по одному (до 10 файлов). Потом нажми «✅ Готово».", reply_markup=done_cancel_kb())
    await callback.answer()


@product_router.callback_query(AddProductStates.ask_photos, F.data == "owner:photos:skip")
async def owner_photos_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(media=[])
    await state.set_state(AddProductStates.enter_sizes)
    await callback.message.edit_text("Введи размеры через запятую (например: 48, 50, 52):", reply_markup=cancel_kb())
    await callback.answer()


@product_router.message(AddProductStates.upload_photos, F.photo)
async def owner_upload_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    media: List[Dict[str, str]] = data.get("media", [])

    if len(media) >= 10:
        await message.answer("Лимит 10 медиа достигнут. Нажми «✅ Готово».", reply_markup=done_cancel_kb())
        return

    media.append({"file_id": message.photo[-1].file_id, "media_type": "photo"})
    await state.update_data(media=media)
    await message.answer(f"Фото сохранено ({len(media)}/10).", reply_markup=done_cancel_kb())


@product_router.message(AddProductStates.upload_photos, F.video)
async def owner_upload_video(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    media: List[Dict[str, str]] = data.get("media", [])

    if len(media) >= 10:
        await message.answer("Лимит 10 медиа достигнут. Нажми «✅ Готово».", reply_markup=done_cancel_kb())
        return

    media.append({"file_id": message.video.file_id, "media_type": "video"})
    await state.update_data(media=media)
    await message.answer(f"Видео сохранено ({len(media)}/10).", reply_markup=done_cancel_kb())


@product_router.callback_query(AddProductStates.upload_photos, F.data == "owner:photos:done")
async def owner_photos_done(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddProductStates.enter_sizes)
    await callback.message.edit_text("Введи размеры через запятую (например: 48, 50, 52):", reply_markup=cancel_kb())
    await callback.answer()


@product_router.message(AddProductStates.enter_sizes)
async def owner_enter_sizes(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if _is_cancel_or_back_text(message.text):
        await state.clear()
        await owner_menu_products(message, state, session)
        return

    parts = [p for p in message.text.replace(" ", "").split(",") if p]
    if not parts:
        await message.answer("Не удалось распознать размеры. Введи через запятую:", reply_markup=cancel_kb())
        return

    await state.update_data(sizes=parts, quantities={}, current_size_index=0)
    await state.set_state(AddProductStates.enter_quantity_for_size)
    await message.answer(f"Введи количество для размера {parts[0]}:", reply_markup=cancel_kb())


@product_router.message(AddProductStates.enter_quantity_for_size)
async def owner_enter_quantity_for_size(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if _is_cancel_or_back_text(message.text):
        await state.clear()
        await owner_menu_products(message, state, session)
        return

    data = await state.get_data()
    sizes = data.get("sizes", [])
    idx = data.get("current_size_index", 0)
    
    try:
        qty = int(message.text.replace(" ", ""))
        if qty < 0: raise ValueError
    except ValueError:
        await message.answer(f"Введи целое число для размера {sizes[idx]}:", reply_markup=cancel_kb())
        return

    quantities = data.get("quantities", {})
    quantities[sizes[idx]] = qty
    idx += 1

    if idx < len(sizes):
        await state.update_data(quantities=quantities, current_size_index=idx)
        await message.answer(f"Введи количество для размера {sizes[idx]}:", reply_markup=cancel_kb())
    else:
        await state.update_data(quantities=quantities)
        await create_product_in_db(message, state, session)


async def create_product_in_db(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Сохранение товара в БД и РАССЫЛКА уведомления."""
    data = await state.get_data()
    repo = await _get_catalog_repo(session)

    cat = await repo.get_category(data["category_id"])
    brand = await repo.get_brand(data["brand_id"])
    if cat is None or brand is None:
        await state.clear()
        await message.answer("⚠️ Категория или бренд не найдены в текущем магазине. Создай их заново.")
        await show_owner_main_menu(message)
        return

    product = await repo.create_product(
        title=data["name"],
        purchase_price=data["purchase_price"],
        sale_price=data["sale_price"],
        category=cat,
        brand=brand,
    )

    media_items = data.get("media")
    if not media_items and data.get("photos"):
        media_items = [{"file_id": file_id, "media_type": "photo"} for file_id in data.get("photos", [])]

    for media in media_items or []:
        await repo.add_photo(
            product=product,
            file_id=media["file_id"],
            media_type=media.get("media_type", "photo"),
        )

    for size in data.get("sizes", []):
        qty = data["quantities"].get(size, 0)
        if qty > 0:
            await repo.add_stock(product=product, size=size, quantity=qty)

    await session.commit()

    # --- РАССЫЛКА ---
    tenant = await get_runtime_tenant(session)
    users_stmt = select(User.tg_id).where(User.tenant_id == tenant.id, User.tg_id.is_not(None))
    users_ids = [uid for uid in (await session.execute(users_stmt)).scalars().all() if uid]
    staff_ids = await list_tenant_recipient_ids(session, tenant.id)
    notify_ids = list(dict.fromkeys([*users_ids, *staff_ids]))
    
    notify_text = (
        f"🔥 <b>НОВИНКА!</b>\n"
        f"🏷 <b>{product.title}</b>\n"
        f"📂 {cat.name} | {brand.name}\n"
        f"💰 <b>{product.sale_price} ₽</b>"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="🛍 Перейти в каталог", callback_data=f"cat:{cat.id}")
    
    async def _broadcast_new_product() -> None:
        sent_count = 0
        for uid in notify_ids:
            try:
                first_media = (media_items or [None])[0]
                if first_media:
                    if normalize_media_type(first_media.get("media_type")) == "video":
                        await message.bot.send_video(
                            uid,
                            video=first_media["file_id"],
                            caption=notify_text,
                            reply_markup=kb.as_markup(),
                            parse_mode="HTML",
                        )
                    else:
                        await message.bot.send_photo(
                            uid,
                            photo=first_media["file_id"],
                            caption=notify_text,
                            reply_markup=kb.as_markup(),
                            parse_mode="HTML",
                        )
                else:
                    await message.bot.send_message(
                        uid,
                        text=notify_text,
                        reply_markup=kb.as_markup(),
                        parse_mode="HTML",
                    )
                sent_count += 1
                await asyncio.sleep(0.05)
            except Exception:
                continue

        await message.bot.send_message(
            message.chat.id,
            f"✅ <b>Рассылка завершена!</b>\n📢 Отправлено: {sent_count} чел.",
            parse_mode="HTML",
        )

    await state.clear()
    if notify_ids:
        await message.answer(
            f"✅ <b>Товар добавлен!</b>\n📢 Запускаю рассылку на {len(notify_ids)} чел.",
            parse_mode="HTML",
        )
        asyncio.create_task(_broadcast_new_product())
    else:
        await message.answer("✅ <b>Товар добавлен!</b>", parse_mode="HTML")

    await show_owner_main_menu(message)


# ==========================================
#          РЕДАКТИРОВАНИЕ ТОВАРА
# ==========================================

@product_router.message(F.text == "✏️ Редактировать товар")
@owner_only
async def owner_edit_start(message: Message, state: FSMContext, session: AsyncSession):
    repo = await _get_catalog_repo(session)
    categories = await repo.list_categories()
    if not categories:
        await message.answer("Категории не найдены.")
        return
    kb = build_categories_kb(list(categories))
    await state.clear()
    await state.set_state(EditProductStates.choose_category)
    await message.answer("🛠 Редактор\nВыберите категорию:", reply_markup=kb)

@product_router.callback_query(EditProductStates.choose_category, F.data.startswith("owner:cat:"))
async def owner_edit_cat(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    cat_id = int(callback.data.split(":")[-1])
    await state.update_data(category_id=cat_id)
    repo = await _get_catalog_repo(session)
    brands = await repo.get_brands_by_category(cat_id)
    kb = build_brands_kb(list(brands))
    await state.set_state(EditProductStates.choose_brand)
    await callback.message.edit_text("Выберите бренд:", reply_markup=kb)

@product_router.callback_query(EditProductStates.choose_brand, F.data.startswith("owner:brand:"))
async def owner_edit_brand(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    brand_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    repo = await _get_catalog_repo(session)
    products = await repo.list_products_by_category_brand(data["category_id"], brand_id)
    if not products:
        await callback.message.edit_text("Товары не найдены.", reply_markup=None)
        return
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(text=p.title, callback_data=f"owner:edit_prod:{p.id}")
    kb.button(text="↩️ Назад", callback_data="owner:cancel")
    kb.adjust(1)
    await state.set_state(EditProductStates.choose_product)
    await callback.message.edit_text("Выберите товар для редактирования:", reply_markup=kb.as_markup())

@product_router.callback_query(F.data.startswith("owner:edit_prod:"))
async def owner_show_edit_card(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if callback.data.startswith("owner:edit_prod:"):
        suffix = callback.data.split(":")[-1]
        if suffix.isdigit():
            product_id = int(suffix)
            await state.update_data(product_id=product_id)
        else:
            product_id = (await state.get_data()).get("product_id")
    else:
        product_id = (await state.get_data()).get("product_id")

    if product_id is None:
        await callback.answer("Товар не найден", show_alert=True)
        return

    repo = await _get_catalog_repo(session)
    product = await repo.get_product_with_details(product_id)
    
    if not product:
        await callback.answer("Товар не найден")
        return

    sizes_info = ", ".join([f"{s.size} ({s.quantity}шт)" for s in product.stock if s.quantity > 0]) or "Нет"
    text = (
        f"🛠 <b>Редактор товара #{product.id}</b>\n"
        f"🏷 <b>{product.title}</b>\n"
        f"🏷️ Бренд: {product.brand.name if product.brand else 'Бренд не указан'}\n"
        f"🔖 SKU: <code>{product.sku}</code>\n"
        f"📂 {product.category.name} | {product.brand.name}\n\n"
        f"💵 Закупка: {product.purchase_price} ₽\n"
        f"💰 Продажа: {product.sale_price} ₽\n"
        f"📦 Остатки: {sizes_info}\n\n"
        f"📝 Описание: {product.description or 'Нет'}"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Изм. Цену", callback_data="edit:action:price")
    kb.button(text="📦 Изм. Остатки", callback_data="edit:action:stock")
    kb.button(text="📝 Изм. Описание", callback_data="edit:action:desc")
    kb.button(text="🖼 Добавить медиа", callback_data="edit:action:photo")
    if product.photos:
        kb.button(text="🗑 Удалить медиа", callback_data="edit:action:photo_delete")
    kb.button(text="🔙 Назад к списку", callback_data="owner:cancel")
    kb.adjust(2, 2, 2)

    await state.set_state(EditProductStates.view_product)
    
    if product.photos:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await _send_product_media_preview(callback.message, list(product.photos), text, kb.as_markup())
    else:
        if callback.message.photo or callback.message.video:
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        else:
            await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()

@product_router.callback_query(F.data == "edit:action:price")
async def start_edit_price(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductStates.edit_price)
    await callback.message.answer("Введите новые цены через пробел:\nFormat: <code>ЗАКУПКА ПРОДАЖА</code>", parse_mode="HTML", reply_markup=cancel_kb())
    await callback.answer()

@product_router.message(EditProductStates.edit_price)
async def process_edit_price(message: Message, state: FSMContext, session: AsyncSession):
    text = _normalize_text(message.text)

    if _is_staff_menu_text(text):
        await state.clear()
        await _maybe_show_staff_menu(message, session)
        return

    # 👇 ЗАЩИТА ОТ КНОПОК
    if _is_cancel_or_back_text(text):
        await state.clear()
        await message.answer("Редактирование цены отменено.")
        if await _maybe_show_staff_menu(message, session):
            return
        await _show_products_menu(message)
        return
    # 👆

    try:
        parts = text.split()
        if len(parts) != 2:
            raise ValueError
        new_purchase = float(parts[0].replace(",", "."))
        new_sale = float(parts[1].replace(",", "."))
        
        repo = await _get_catalog_repo(session)
        data = await state.get_data()
        await repo.update_product_prices(data["product_id"], new_purchase, new_sale)
        await session.commit()
        
        await message.answer("✅ Цены обновлены.")
        if await _maybe_show_staff_menu(message, session):
            await state.clear()
            return
        await owner_show_edit_card_manual(message, state, session)
    except ValueError:
        await message.answer("⚠️ Ошибка. Введите два числа через пробел или нажмите «↩️ Назад».")

@product_router.callback_query(F.data == "edit:action:desc")
async def start_edit_desc(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductStates.edit_description)
    await callback.message.answer("Введите новое описание (или '-' чтобы удалить):", reply_markup=cancel_kb())
    await callback.answer()

@product_router.message(EditProductStates.edit_description)
async def process_edit_desc(message: Message, state: FSMContext, session: AsyncSession):
    desc = _normalize_text(message.text)

    if _is_staff_menu_text(desc):
        await state.clear()
        await _maybe_show_staff_menu(message, session)
        return
    
    # 👇 ДОБАВЛЕНА ПРОВЕРКА НА КНОПКИ ОТМЕНЫ
    if _is_cancel_or_back_text(desc) or desc == "owner:cancel":
        await state.clear()
        await message.answer("Редактирование описания отменено.")
        if await _maybe_show_staff_menu(message, session):
            return
        await _show_products_menu(message)
        return
    # 👆 КОНЕЦ ПРОВЕРКИ

    if desc == "-": 
        desc = None
        
    repo = await _get_catalog_repo(session)
    # Получаем ID из состояния
    data = await state.get_data()
    product_id = data.get("product_id")
    
    await repo.update_product_description(product_id, desc)
    await session.commit()
    
    await message.answer("✅ Описание обновлено.")
    if await _maybe_show_staff_menu(message, session):
        await state.clear()
        return
    await owner_show_edit_card_manual(message, state, session)

@product_router.callback_query(F.data == "edit:action:stock")
async def start_edit_stock(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    repo = await _get_catalog_repo(session)
    product = await repo.get_product_with_details((await state.get_data())["product_id"])
    kb = InlineKeyboardBuilder()
    for s in product.stock:
        kb.button(text=f"{s.size} (сейчас: {s.quantity})", callback_data=f"stock:edit:{s.size}")
    kb.button(text="➕ Добавить размер", callback_data="stock:new")
    kb.button(text="🔙 Назад", callback_data="owner:edit_prod:back") 
    kb.adjust(1)
    await state.set_state(EditProductStates.choose_size_to_edit)
    if callback.message.photo: await callback.message.delete(); await callback.message.answer("Редактор склада:", reply_markup=kb.as_markup())
    else: await callback.message.edit_text("Редактор склада:", reply_markup=kb.as_markup())
    await callback.answer()

@product_router.callback_query(F.data.startswith("stock:edit:"))
async def stock_edit_size_chosen(callback: CallbackQuery, state: FSMContext):
    await state.update_data(editing_size=callback.data.split(":")[-1])
    await state.set_state(EditProductStates.edit_stock_qty)
    await callback.message.answer("Введите новое количество (целое число):", reply_markup=cancel_kb())
    await callback.answer()

@product_router.callback_query(F.data == "stock:new")
async def stock_new_size(callback: CallbackQuery, state: FSMContext):
    await state.update_data(editing_size=None)
    await state.set_state(EditProductStates.edit_stock_qty)
    await callback.message.answer("Введите: РАЗМЕР КОЛИЧЕСТВО", reply_markup=cancel_kb())
    await callback.answer()

@product_router.callback_query(F.data == "owner:edit_prod:back")
async def back_to_card_from_stock(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    await owner_show_edit_card(callback, state, session)

@product_router.message(EditProductStates.edit_stock_qty)
async def process_stock_update(message: Message, state: FSMContext, session: AsyncSession):
    text = _normalize_text(message.text)

    if _is_staff_menu_text(text):
        await state.clear()
        await _maybe_show_staff_menu(message, session)
        return

    # 👇 ЗАЩИТА ОТ КНОПОК
    if _is_cancel_or_back_text(text):
        await state.clear()
        await message.answer("Редактирование остатков отменено.")
        if await _maybe_show_staff_menu(message, session):
            return
        await _show_products_menu(message)
        return
    # 👆

    data = await state.get_data()
    pid = data.get("product_id")
    editing_size = data.get("editing_size")
    
    repo = await _get_catalog_repo(session)
    
    try:
        if editing_size:
            # Обновляем существующий размер
            qty = int(text)
            if qty < 0: raise ValueError
            await repo.update_stock_quantity(pid, editing_size, qty)
            await session.commit()
            await message.answer(f"✅ Для размера {editing_size} установлено количество {qty}.")
        else:
            # Добавляем новый
            parts = text.split()
            if len(parts) != 2: raise ValueError
            size = parts[0]
            qty = int(parts[1])
            await repo.update_stock_quantity(pid, size, qty)
            await session.commit()
            await message.answer(f"✅ Размер {size} добавлен ({qty} шт).")
            
        await owner_show_edit_card_manual(message, state, session)
    except ValueError:
        await message.answer("⚠️ Ошибка ввода. Проверьте формат или нажмите «↩️ Назад».")

@product_router.callback_query(F.data == "edit:action:photo")
async def start_add_photo(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductStates.wait_for_new_photo)
    await callback.message.answer("📸 Отправь новое фото или видео:", reply_markup=cancel_kb())
    await callback.answer()

@product_router.callback_query(F.data == "edit:action:photo_delete")
async def start_delete_photo(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    repo = await _get_catalog_repo(session)
    product_id = (await state.get_data()).get("product_id")
    product = await repo.get_product_with_details(product_id)
    if not product or not product.photos:
        await callback.answer("Нет медиа для удаления", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    media_lines = []
    for idx, ph in enumerate(product.photos, 1):
        media_label = "Видео" if normalize_media_type(getattr(ph, "media_type", None)) == "video" else "Фото"
        kb.button(text=f"🗑 {media_label} {idx}", callback_data=f"edit:photo:del:{ph.id}")
        media_lines.append(describe_media_item(ph, idx))
    kb.button(text="🔙 Назад", callback_data="owner:edit_prod:back")
    kb.adjust(1)

    await state.set_state(EditProductStates.choose_photo_to_delete)
    preview_text = (
        f"🧩 <b>Медиа товара #{product.id}</b>\n"
        f"🏷 <b>{product.title}</b>\n\n"
        f"Доступные файлы:\n" + "\n".join(media_lines) + "\n\n"
        f"Выберите файл для удаления кнопкой ниже."
    )
    await _send_product_media_preview(callback.message, list(product.photos), preview_text, kb.as_markup())
    await callback.answer()

@product_router.callback_query(F.data.startswith("edit:photo:del:"))
async def delete_photo_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    photo_id = int(callback.data.split(":")[-1])
    repo = await _get_catalog_repo(session)
    if not await repo.delete_photo(photo_id):
        await callback.answer("Медиа не найдено", show_alert=True)
        return
    await session.commit()
    await callback.message.answer("✅ Медиа удалено!")
    if await _maybe_show_staff_menu(callback.message, session):
        await state.clear()
        return
    await owner_show_edit_card_manual(callback.message, state, session)
    await callback.answer()

@product_router.message(EditProductStates.wait_for_new_photo, F.photo)
async def process_add_photo_edit(message: Message, state: FSMContext, session: AsyncSession):
    repo = await _get_catalog_repo(session)
    prod = await repo.get_product_with_details((await state.get_data())["product_id"])
    await repo.add_photo(prod, message.photo[-1].file_id, media_type="photo")
    await session.commit()
    await message.answer("✅ Фото добавлено!")
    if await _maybe_show_staff_menu(message, session):
        await state.clear()
        return
    await owner_show_edit_card_manual(message, state, session)


@product_router.message(EditProductStates.wait_for_new_photo, F.video)
async def process_add_video_edit(message: Message, state: FSMContext, session: AsyncSession):
    repo = await _get_catalog_repo(session)
    prod = await repo.get_product_with_details((await state.get_data())["product_id"])
    await repo.add_photo(prod, message.video.file_id, media_type="video")
    await session.commit()
    await message.answer("✅ Видео добавлено!")
    if await _maybe_show_staff_menu(message, session):
        await state.clear()
        return
    await owner_show_edit_card_manual(message, state, session)

# --- Вспомогательная функция (Ручной возврат в карточку) ---
async def owner_show_edit_card_manual(message: Message, state: FSMContext, session: AsyncSession):
    # Хак для вызова колбэка через сообщение (чтобы не дублировать код карточки)
    # Создаем фейковый callback
    class FakeCallback:
        # 👇 ИСПРАВЛЕНО: используем "refresh_view" вместо "owner:edit_prod:current"
        # Это заставит функцию owner_show_edit_card брать ID из памяти (state), а не парсить строку
        def __init__(self, msg): self.message, self.data = msg, "refresh_view"
        async def answer(self, *args, **kwargs): pass
    
    await owner_show_edit_card(FakeCallback(message), state, session)