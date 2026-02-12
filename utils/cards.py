from __future__ import annotations

from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.media_group import MediaGroupBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from database.catalog_repo import CatalogRepo


async def send_product_card(
    chat_id: int,
    bot: Bot,
    product_id: int,
    session: AsyncSession,
    is_ai_mode: bool = False
) -> None:
    """
    Универсальная функция отправки карточки товара.
    Используется и в AI-режиме, и в обычном каталоге.
    """
    repo = CatalogRepo(session)
    product = await repo.get_product_with_details(product_id)
    
    if not product:
        return

    available_sizes = [f"{s.size}" for s in product.stock if s.quantity > 0]
    sizes_str = ", ".join(available_sizes) if available_sizes else "Нет в наличии"

    text = (
        f"🏷 {product.title}\n\n"
        f"💰 Цена: {product.sale_price} ₽\n"
        f"📏 Размеры в наличии: {sizes_str}\n"
    )
    if product.description:
        text += f"\nℹ️ {product.description}"

    kb = InlineKeyboardBuilder()
    if available_sizes:
        if is_ai_mode:
            kb.button(text="🛒 В корзину", callback_data=f"ai_cart_add:{product_id}")
        else:
            kb.button(text="🛒 В корзину", callback_data=f"cart:add:{product_id}")
    else:
        kb.button(text="🚫 Нет в наличии", callback_data="ignore")
    
    if is_ai_mode:
        kb.button(text="🔙 Вернуться в чат", callback_data="ai_back_to_chat")
    else:
        kb.button(text="⬅ Назад", callback_data=f"back:products:{product.category_id}:{product.brand_id}")
    
    kb.adjust(1)

    if product.photos:
        if len(product.photos) > 1:
            album = MediaGroupBuilder(caption=text)
            for ph in product.photos:
                album.add_photo(media=ph.file_id)
            
            await bot.send_media_group(chat_id=chat_id, media=album.build())
            await bot.send_message(chat_id, "👇 Действия:", reply_markup=kb.as_markup())
        else:
            await bot.send_photo(
                chat_id=chat_id,
                photo=product.photos[0].file_id,
                caption=text,
                reply_markup=kb.as_markup()
            )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=kb.as_markup()
        )