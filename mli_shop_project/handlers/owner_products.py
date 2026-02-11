"""Хэндлеры добавления и редактирования товара для владельца."""

from typing import Any, Dict, List
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder 

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.catalog_repo import CatalogRepo
from models.catalog import Category, Brand, Product
from models.users import User

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
from .owner_utils import ensure_owner, show_owner_main_menu

product_router = Router(name="owner_products")


# ==========================================
#          ГЛАВНОЕ МЕНЮ ТОВАРОВ
# ==========================================

@product_router.message(F.text == "📦 Товары")
async def owner_menu_products(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Меню управления товарами."""
    if not await ensure_owner(message, session):
        return

    kb = owner_products_menu_kb()
    await message.answer(
        "📦 Управление товарами:\n\nВыбери действие:",
        reply_markup=kb,
    )


# ==========================================
#          ДОБАВЛЕНИЕ КАТЕГОРИИ
# ==========================================

@product_router.message(F.text == "➕ Добавить категорию")
async def owner_add_category_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Начало добавления категории."""
    if not await ensure_owner(message, session):
        return

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
    if name == "⬅ Назад" or name == "❌ Отмена":
        await state.clear()
        await owner_menu_products(message, state)
        return

    # Переключение на другие функции
    if name == "➕ Добавить бренд":
        await state.clear()
        await owner_add_brand_start(message, state)
        return
    if name == "➕ Добавить товар":
        await state.clear()
        await owner_menu_products(message, state)
        return

    # Защита от названий кнопок
    forbidden_names = ["✏️ Редактировать товар", "❌ Удалить товар", "➕ Добавить товар", "🗑 Удалить категорию", "🗑 Удалить бренд"]
    if name in forbidden_names:
        await message.answer("❌ Нельзя называть категорию именем кнопки! Введи название текстом:")
        return

    if not name:
        await message.answer("Название категории не может быть пустым. Введи ещё раз:", reply_markup=cancel_kb())
        return

    repo = CatalogRepo(session)
    await repo.get_or_create_category(name=name)
    await session.commit()

    await state.clear()
    await message.answer(f"✅ Категория «{name}» добавлена.")
    await owner_menu_products(message, state)


# ==========================================
#          ДОБАВЛЕНИЕ БРЕНДА
# ==========================================

@product_router.message(F.text == "➕ Добавить бренд")
async def owner_add_brand_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Начало добавления бренда."""
    if not await ensure_owner(message, session):
        return

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
    if name == "⬅ Назад" or name == "❌ Отмена":
        await state.clear()
        await owner_menu_products(message, state)
        return

    # Переключение на другие функции
    if name == "➕ Добавить категорию":
        await state.clear()
        await owner_add_category_start(message, state)
        return
    if name == "➕ Добавить товар":
        await state.clear()
        await owner_menu_products(message, state)
        return

    # Защита от названий кнопок
    forbidden_names = ["✏️ Редактировать товар", "❌ Удалить товар", "➕ Добавить товар", "🗑 Удалить категорию", "🗑 Удалить бренд"]
    if name in forbidden_names:
        await message.answer("❌ Нельзя называть бренд именем кнопки! Введи название текстом:")
        return

    if not name:
        await message.answer("Название бренда не может быть пустым. Введи ещё раз:", reply_markup=cancel_kb())
        return

    repo = CatalogRepo(session)
    await repo.get_or_create_brand(name=name)
    await session.commit()

    await state.clear()
    await message.answer(f"✅ Бренд «{name}» добавлен.")
    await owner_menu_products(message, state)


# ==========================================
#          ДОБАВЛЕНИЕ ТОВАРА
# ==========================================

@product_router.message(F.text == "➕ Добавить товар")
async def owner_add_product_start(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Начало добавления товара."""
    if not await ensure_owner(message, session):
        return

    repo = CatalogRepo(session)
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

    repo = CatalogRepo(session)
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
async def owner_enter_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if name == "⬅ Назад" or name == "❌ Отмена":
        await state.clear()
        await owner_menu_products(message, state)
        return

    forbidden_names = ["✏️ Редактировать товар", "❌ Удалить товар", "➕ Добавить товар", "🗑 Удалить категорию", "🗑 Удалить бренд"]
    if name in forbidden_names:
        await message.answer("❌ Нельзя называть товар именем кнопки! Введи название текстом:")
        return

    if not name:
        await message.answer("Название не может быть пустым.", reply_markup=cancel_kb())
        return

    await state.update_data(name=name)
    await state.set_state(AddProductStates.enter_purchase_price)
    await message.answer("Введи закупочную цену (число):", reply_markup=cancel_kb())


@product_router.message(AddProductStates.enter_purchase_price)
async def owner_enter_purchase_price(message: Message, state: FSMContext) -> None:
    try:
        value = float(message.text.replace(" ", "").replace(",", "."))
        if value < 0: raise ValueError
    except ValueError:
        await message.answer("Некорректное число. Введи закупочную цену ещё раз:", reply_markup=cancel_kb())
        return

    await state.update_data(purchase_price=value)
    await state.set_state(AddProductStates.enter_sale_price)
    await message.answer("Введи продажную цену (число):", reply_markup=cancel_kb())


@product_router.message(AddProductStates.enter_sale_price)
async def owner_enter_sale_price(message: Message, state: FSMContext) -> None:
    try:
        value = float(message.text.replace(" ", "").replace(",", "."))
        if value < 0: raise ValueError
    except ValueError:
        await message.answer("Некорректное число. Введи продажную цену ещё раз:", reply_markup=cancel_kb())
        return

    await state.update_data(sale_price=value)
    await state.set_state(AddProductStates.ask_photos)
    await message.answer("Добавить фото товара? Можно до 10 фото.", reply_markup=yes_no_cancel_kb())


@product_router.callback_query(AddProductStates.ask_photos, F.data == "owner:photos:yes")
async def owner_photos_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(photos=[])
    await state.set_state(AddProductStates.upload_photos)
    await callback.message.edit_text("Отправляй фото по одному (до 10 шт). Потом нажми «✅ Готово».", reply_markup=done_cancel_kb())
    await callback.answer()


@product_router.callback_query(AddProductStates.ask_photos, F.data == "owner:photos:skip")
async def owner_photos_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(photos=[])
    await state.set_state(AddProductStates.enter_sizes)
    await callback.message.edit_text("Введи размеры через запятую (например: 48, 50, 52):", reply_markup=cancel_kb())
    await callback.answer()


@product_router.message(AddProductStates.upload_photos, F.photo)
async def owner_upload_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photos: List[str] = data.get("photos", [])

    if len(photos) >= 10:
        await message.answer("Лимит 10 фото достигнут. Нажми «✅ Готово».", reply_markup=done_cancel_kb())
        return

    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer(f"Фото сохранено ({len(photos)}/10).", reply_markup=done_cancel_kb())


@product_router.callback_query(AddProductStates.upload_photos, F.data == "owner:photos:done")
async def owner_photos_done(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddProductStates.enter_sizes)
    await callback.message.edit_text("Введи размеры через запятую (например: 48, 50, 52):", reply_markup=cancel_kb())
    await callback.answer()


@product_router.message(AddProductStates.enter_sizes)
async def owner_enter_sizes(message: Message, state: FSMContext) -> None:
    parts = [p for p in message.text.replace(" ", "").split(",") if p]
    if not parts:
        await message.answer("Не удалось распознать размеры. Введи через запятую:", reply_markup=cancel_kb())
        return

    await state.update_data(sizes=parts, quantities={}, current_size_index=0)
    await state.set_state(AddProductStates.enter_quantity_for_size)
    await message.answer(f"Введи количество для размера {parts[0]}:", reply_markup=cancel_kb())


@product_router.message(AddProductStates.enter_quantity_for_size)
async def owner_enter_quantity_for_size(message: Message, state: FSMContext, session: AsyncSession) -> None:
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
    repo = CatalogRepo(session)

    # Загружаем объекты
    cat = (await session.execute(select(Category).where(Category.id == data["category_id"]))).scalar_one()
    brand = (await session.execute(select(Brand).where(Brand.id == data["brand_id"]))).scalar_one()

    product = await repo.create_product(
        title=data["name"],
        purchase_price=data["purchase_price"],
        sale_price=data["sale_price"],
        category=cat,
        brand=brand,
    )

    for photo_id in data.get("photos", []):
        await repo.add_photo(product=product, file_id=photo_id)

    for size in data.get("sizes", []):
        qty = data["quantities"].get(size, 0)
        if qty > 0:
            await repo.add_stock(product=product, size=size, quantity=qty)

    await session.commit()

    # --- РАССЫЛКА ---
    from config import settings
    users_ids = (await session.execute(select(User.tg_id).where(User.tg_id != settings.owner_id))).scalars().all()
    staff_ids = (await session.execute(
        select(User.tg_id).where(User.role == UserRole.STAFF.value)
    )).scalars().all()
    notify_ids = list(dict.fromkeys([*users_ids, *staff_ids]))
    
    notify_text = (
        f"🔥 <b>НОВИНКА!</b>\n"
        f"🏷 <b>{product.title}</b>\n"
        f"📂 {cat.name} | {brand.name}\n"
        f"💰 <b>{product.sale_price} ₽</b>"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="🛍 Перейти в каталог", callback_data=f"cat:{cat.id}")
    
    sent_count = 0
    if notify_ids:
        status_msg = await message.answer(f"⏳ Рассылка для {len(notify_ids)} чел...")
        for uid in notify_ids:
            try:
                if data.get("photos"):
                    await message.bot.send_photo(uid, photo=data["photos"][0], caption=notify_text, reply_markup=kb.as_markup(), parse_mode="HTML")
                else:
                    await message.bot.send_message(uid, text=notify_text, reply_markup=kb.as_markup(), parse_mode="HTML")
                sent_count += 1
                import asyncio
                await asyncio.sleep(0.05)
            except: pass
        try: await status_msg.delete() 
        except: pass

    await state.clear()
    await message.answer(f"✅ <b>Товар добавлен!</b>\n📢 Отправлено: {sent_count} чел.", parse_mode="HTML")
    await show_owner_main_menu(message)


# ==========================================
#          РЕДАКТИРОВАНИЕ ТОВАРА
# ==========================================

@product_router.message(F.text == "✏️ Редактировать товар")
async def owner_edit_start(message: Message, state: FSMContext, session: AsyncSession):
    if not await ensure_owner(message, session):
        return
    repo = CatalogRepo(session)
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
    repo = CatalogRepo(session)
    brands = await repo.get_brands_by_category(cat_id)
    kb = build_brands_kb(list(brands))
    await state.set_state(EditProductStates.choose_brand)
    await callback.message.edit_text("Выберите бренд:", reply_markup=kb)

@product_router.callback_query(EditProductStates.choose_brand, F.data.startswith("owner:brand:"))
async def owner_edit_brand(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    brand_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    repo = CatalogRepo(session)
    products = await repo.list_products_by_category_brand(data["category_id"], brand_id)
    if not products:
        await callback.message.edit_text("Товары не найдены.", reply_markup=None)
        return
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(text=p.title, callback_data=f"owner:edit_prod:{p.id}")
    kb.button(text="❌ Отмена", callback_data="owner:cancel")
    kb.adjust(1)
    await state.set_state(EditProductStates.choose_product)
    await callback.message.edit_text("Выберите товар для редактирования:", reply_markup=kb.as_markup())

@product_router.callback_query(F.data.startswith("owner:edit_prod:"))
async def owner_show_edit_card(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if "owner:edit_prod:" in callback.data:
        product_id = int(callback.data.split(":")[-1])
        await state.update_data(product_id=product_id)
    else:
        product_id = (await state.get_data()).get("product_id")

    repo = CatalogRepo(session)
    product = await repo.get_product_with_details(product_id)
    
    if not product:
        await callback.answer("Товар не найден")
        return

    sizes_info = ", ".join([f"{s.size} ({s.quantity}шт)" for s in product.stock if s.quantity > 0]) or "Нет"
    text = (
        f"🛠 <b>Редактор товара #{product.id}</b>\n"
        f"🏷 <b>{product.title}</b>\n"
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
    kb.button(text="🖼 Добавить фото", callback_data="edit:action:photo")
    kb.button(text="🔙 Назад к списку", callback_data="owner:cancel")
    kb.adjust(2, 2, 1)

    await state.set_state(EditProductStates.view_product)
    
    if product.photos:
        if callback.message.photo:
            try: await callback.message.edit_caption(caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
            except: 
                await callback.message.delete()
                await callback.message.answer_photo(product.photos[0].file_id, caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
        else:
            await callback.message.delete()
            await callback.message.answer_photo(product.photos[0].file_id, caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        if callback.message.photo:
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
    text = message.text.strip()

    # 👇 ЗАЩИТА ОТ КНОПОК
    if text in ["⬅ Назад", "❌ Отмена"]:
        await message.answer("Редактирование цены отменено.")
        await owner_show_edit_card_manual(message, state, session)
        return
    # 👆

    try:
        parts = text.split()
        if len(parts) != 2:
            raise ValueError
        new_purchase = float(parts[0].replace(",", "."))
        new_sale = float(parts[1].replace(",", "."))
        
        repo = CatalogRepo(session)
        data = await state.get_data()
        await repo.update_product_prices(data["product_id"], new_purchase, new_sale)
        await session.commit()
        
        await message.answer("✅ Цены обновлены.")
        await owner_show_edit_card_manual(message, state, session)
    except ValueError:
        await message.answer("❌ Ошибка. Введите два числа через пробел или нажмите «❌ Отмена».")

@product_router.callback_query(F.data == "edit:action:desc")
async def start_edit_desc(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductStates.edit_description)
    await callback.message.answer("Введите новое описание (или '-' чтобы удалить):", reply_markup=cancel_kb())
    await callback.answer()

@product_router.message(EditProductStates.edit_description)
async def process_edit_desc(message: Message, state: FSMContext, session: AsyncSession):
    desc = message.text.strip()
    
    # 👇 ДОБАВЛЕНА ПРОВЕРКА НА КНОПКИ ОТМЕНЫ
    if desc in ["⬅ Назад", "❌ Отмена", "owner:cancel"]:
        await message.answer("Редактирование описания отменено.")
        await owner_show_edit_card_manual(message, state, session)
        return
    # 👆 КОНЕЦ ПРОВЕРКИ

    if desc == "-": 
        desc = None
        
    repo = CatalogRepo(session)
    # Получаем ID из состояния
    data = await state.get_data()
    product_id = data.get("product_id")
    
    await repo.update_product_description(product_id, desc)
    await session.commit()
    
    await message.answer("✅ Описание обновлено.")
    await owner_show_edit_card_manual(message, state, session)

@product_router.callback_query(F.data == "edit:action:stock")
async def start_edit_stock(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    repo = CatalogRepo(session)
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
    text = message.text.strip()

    # 👇 ЗАЩИТА ОТ КНОПОК
    if text in ["⬅ Назад", "❌ Отмена"]:
        await message.answer("Редактирование остатков отменено.")
        await owner_show_edit_card_manual(message, state, session)
        return
    # 👆

    data = await state.get_data()
    pid = data.get("product_id")
    editing_size = data.get("editing_size")
    
    repo = CatalogRepo(session)
    
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
        await message.answer("❌ Ошибка ввода. Проверьте формат или нажмите «❌ Отмена».")

@product_router.callback_query(F.data == "edit:action:photo")
async def start_add_photo(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditProductStates.wait_for_new_photo)
    await callback.message.answer("📸 Отправь НОВОЕ фото:", reply_markup=cancel_kb())
    await callback.answer()

@product_router.message(EditProductStates.wait_for_new_photo, F.photo)
async def process_add_photo_edit(message: Message, state: FSMContext, session: AsyncSession):
    repo = CatalogRepo(session)
    prod = await repo.get_product_with_details((await state.get_data())["product_id"])
    await repo.add_photo(prod, message.photo[-1].file_id)
    await session.commit()
    await message.answer("✅ Фото добавлено!")
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