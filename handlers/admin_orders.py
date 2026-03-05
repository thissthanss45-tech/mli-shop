from __future__ import annotations

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from models import User, UserRole
from models.orders import Order, OrderItem, OrderStatus
from models.catalog import Product
from models.users import normalize_role
from utils.admin_kb import build_active_order_kb

from .owner_states import AdminOrderReplyStates

admin_orders_router = Router(name="admin_orders")


def _orders_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Активные заказы")],
            [KeyboardButton(text="✅ История заказов")],
            [KeyboardButton(text="🔙 Назад")],
        ],
        resize_keyboard=True,
    )


async def _is_owner_or_staff(user_id: int, session: AsyncSession) -> bool:
    if user_id == settings.owner_id:
        return True
    stmt = select(User).where(User.tg_id == user_id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    return bool(user and normalize_role(user.role) == UserRole.STAFF.value)


async def _render_order_card(message: Message, session: AsyncSession, order_id: int) -> None:
    stmt = (
        select(Order)
        .options(
            selectinload(Order.user),
            selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.brand),
        )
        .where(Order.id == order_id)
    )
    order = (await session.execute(stmt)).scalar_one_or_none()
    if not order:
        await message.answer("⚠️ Заказ не найден.")
        return

    lines_list: list[str] = []
    if not order.items:
        lines_list.append("⚠️ <i>Ошибка: Заказ пуст</i>")
    else:
        for item in order.items:
            brand = item.product.brand.name if (item.product and item.product.brand) else "Без бренда"
            title = item.product.title if item.product else "ТОВАР УДАЛЁН"
            price_fmt = f"{item.sale_price:g}"
            lines_list.append(
                f"▫️ <b>{brand} | {title}</b>\n"
                f"   Размер: {item.size} | {item.quantity} шт. | {price_fmt} ₽"
            )

    items_text = "\n".join(lines_list)
    total_fmt = f"{order.total_price:g}"
    card_text = (
        f"🆔 <b>Заказ #{order.id}</b>\n"
        f"👤 {order.full_name}\n"
        f"📱 <code>{order.phone}</code>\n"
        f"💰 Сумма: <b>{total_fmt} ₽</b>\n"
        f"<b>Состав заказа:</b>\n{items_text}"
    )

    sku_items: list[tuple[str, int]] = []
    for item in order.items:
        if item.product and item.product.sku:
            sku_items.append((item.product.sku, item.product.id))

    if order.user and order.user.tg_id:
        markup = build_active_order_kb(order.id, order.user.tg_id, sku_items)
    else:
        kb = InlineKeyboardBuilder()
        for sku, product_id in sku_items:
            kb.button(text=f"📦 {sku}", callback_data=f"prod:0:0:{product_id}")
        kb.button(text="✅ Выполнен", callback_data=f"order:done:{order.id}")
        kb.button(text="🗑 Отменить", callback_data=f"order:cancel:{order.id}")
        kb.adjust(2)
        markup = kb.as_markup()

    await message.answer(card_text, reply_markup=markup, parse_mode="HTML")


@admin_orders_router.callback_query(F.data.startswith("admin_reply_"))
async def admin_reply_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not await _is_owner_or_staff(callback.from_user.id, session):
        await callback.answer("⛔ Только для персонала.", show_alert=True)
        return

    payload = callback.data.removeprefix("admin_reply_")
    parts = payload.split("_")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    target_tg_id = int(parts[0])
    order_id = int(parts[1])

    await state.update_data(reply_to_client_tg_id=target_tg_id, reply_order_id=order_id)
    await state.set_state(AdminOrderReplyStates.waiting_for_message_to_client)

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Назад")]],
        resize_keyboard=True,
    )
    await callback.message.answer(
        f"✉️ Введите сообщение для покупателя {target_tg_id}.\n"
        "Можно отправить текст, фото, голос или другое медиа.",
        reply_markup=kb,
    )
    await callback.answer()


@admin_orders_router.message(AdminOrderReplyStates.waiting_for_message_to_client)
async def admin_reply_send(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if text in {"📋 Заказы", "📋 Активные заказы", "✅ История заказов"}:
        await state.clear()
        await message.answer("Выберите раздел заказов:", reply_markup=_orders_menu_kb())
        return

    if text in {"⬅ Назад", "🔙 Назад", "↩️ Назад", "Отмена"}:
        data = await state.get_data()
        order_id = data.get("reply_order_id")
        await state.clear()
        await message.answer("✅ Отменено.", reply_markup=_orders_menu_kb())
        if order_id:
            await _render_order_card(message, session, int(order_id))
        return

    data = await state.get_data()
    target_tg_id = data.get("reply_to_client_tg_id")
    order_id = data.get("reply_order_id")
    if not target_tg_id or not order_id:
        await state.clear()
        await message.answer("⚠️ Сессия ответа устарела. Откройте заказ заново.")
        return

    prefix = "💬 Сообщение от поддержки:"

    try:
        if message.text:
            await message.bot.send_message(
                chat_id=int(target_tg_id),
                text=f"{prefix}\n{message.text}",
            )
        else:
            await message.bot.send_message(chat_id=int(target_tg_id), text=prefix)
            await message.bot.copy_message(
                chat_id=int(target_tg_id),
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
    except TelegramBadRequest:
        await message.answer("⚠️ Этот тип сообщения не удалось переслать. Отправьте текст или фото/голос.")
        return
    except (TelegramForbiddenError, TelegramNotFound):
        await message.answer("⚠️ Не удалось отправить: пользователь недоступен для бота.")
        return

    await state.clear()
    await message.answer("✅ Сообщение отправлено", reply_markup=_orders_menu_kb())

    await _render_order_card(message, session, int(order_id))
