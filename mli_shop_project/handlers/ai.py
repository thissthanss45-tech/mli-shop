from __future__ import annotations

import logging
import re
import asyncio
import aiohttp
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from database.catalog_repo import CatalogRepo
from database.orders_repo import OrdersRepo
from models import Product, User, UserRole
from models.users import normalize_role
from utils.cards import send_product_card
from utils.sender import send_safe_html

ai_router = Router()

logger = logging.getLogger(__name__)

class AIStates(StatesGroup):
    chatting = State()
    waiting_for_size = State()


def _is_exit_text(text: str) -> bool:
    return text in {
        "❌ Отмена",
        "🔙 Отмена",
        "⬅ Назад",
        "🔙 Назад",
        "🛍 Каталог",
        "📦 Мои заказы",
        "✨ AI-Консультант",
        "🛒 Корзина",
        "📊 Склад",
        "📋 Заказы",
        "📦 Товары",
        "📈 Статистика",
        "🏪 Витрина",
        "➕ Добавить категорию",
        "➕ Добавить бренд",
        "➕ Добавить товар",
        "✏️ Редактировать товар",
        "🗑 Удалить товар",
        "🗑 Удалить категорию",
        "🗑 Удалить бренд",
        "💳 Касса",
    }


def _is_post_request(text: str) -> bool:
    lowered = text.lower()
    return bool(re.search(r"\b(напиши(?:те)?|сделай|создай)\s+пост\b", lowered)) or (
        "пост" in lowered and any(word in lowered for word in ["реклам", "рассыл", "smm", "промо", "пост"])
    )

PROMPT_CLIENT = """
Твоя роль: Элитный продавец-консультант бутика.
Твоя цель: Вежливо помочь клиенту выбрать товар, подобрать размер и продать.
Тон: Уважительный, услужливый, краткий.

ИНСТРУКЦИИ:
1. Используй контекст ниже ("НАШ АССОРТИМЕНТ"), чтобы отвечать на вопросы о наличии.
2. Если товара нет в списке — извинись и предложи посмотреть каталог.
3. Если клиент просит показать товар, найди его ID и вставь тег [SHOW_ID: 123].
4. Не показывай закупочные цены! Клиент видит только цену продажи.
5. ВАЖНО: При написании постов (маркетинговых текстов) НИКОГДА не упоминай закупочные цены, прибыль или выручку! Клиенты не должны видеть внутреннюю кухню.

НАШ АССОРТИМЕНТ:
{context_data}
"""

PROMPT_OWNER = """
Твоя роль: Опытный бизнес-аналитик и SMM-менеджер бутика.

ТВОИ РЕЖИМЫ РАБОТЫ:
1. 📊 АНАЛИТИКА (Если спрашивают про деньги/склад):
   - Будь жестким и точным. Используй цифры, ID, остатки.
   - Указывай на "мертвый груз" (много остатка, 0 продаж).
   - Советуй закупки.

2. ✍️ SMM / ПОСТЫ (Если просят написать пост/рекламу):
   - ⛔️ ЗАПРЕЩЕНО писать ID товаров, точные остатки (напр. "осталось 5 шт"), количество продаж.
   - ⛔️ ЗАПРЕЩЕНО использовать слова "Неликвид", "Закупка", "Прибыль".
   - ⛔️ ЗАПРЕЩЕНО придумывать бренды (используй только те, что в списке "ПРЕДСТАВЛЕННЫЕ БРЕНДЫ").
    - Пиши эмоционально, "дорого", продавай стиль и образ жизни.
    - Обязательно добавляй уместные иконки (эмодзи) в тексте поста.

ИНСТРУКЦИИ:
1. В отчете ниже ты видишь поле [ПРОДАНО: X шт].
2. Если [ПРОДАНО] высокое, а [ОСТАТОК] низкий — советуй срочно докупить (Best Seller).
3. Если [ПРОДАНО: 0], а [ОСТАТОК] большой — это "неликвид".
4. Если спрашивают "Как дела?", дай сводку с цифрами.
5. Если просят "Напиши пост", забудь про цифры и включай режим креатива.

ФИНАНСОВЫЙ И СКЛАДСКОЙ ОТЧЕТ:
{context_data}
"""

async def get_client_context(session: AsyncSession) -> str:
    repo = CatalogRepo(session)
    products = await repo.get_all_products_with_stock()
    
    if not products:
        return "Каталог пуст."

    lines = []
    for p in products:
        total_qty = sum(s.quantity for s in p.stock)
        if total_qty > 0:
            sizes = ", ".join([s.size for s in p.stock if s.quantity > 0])
            brand = p.brand.name if p.brand else "Бренд"
            lines.append(f"• [ID: {p.id}] {brand} {p.title} | {p.sale_price} руб. | Размеры: {sizes}")
    
    return "\n".join(lines)


async def get_owner_context(session: AsyncSession) -> str:
    catalog_repo = CatalogRepo(session)
    orders_repo = OrdersRepo(session)

    # 1. Общие продажи (за всё время) для анализа неликвида
    sales_map = await orders_repo.get_sales_summary_by_product()
    
    # 2. Общая финансовая сводка (За всё время)
    global_stats = await orders_repo.get_stats_for_period(datetime(2020, 1, 1), datetime.utcnow())
    
    # 3. 🔥 СТАТИСТИКА ЗА СЕГОДНЯ (ДЕТАЛЬНО)
    today_details = await orders_repo.get_today_sales_details()

    # 👇 4. НОВОЕ: ПОЛУЧАЕМ ВСЕ БРЕНДЫ 👇
    all_brands = await catalog_repo.list_brands()
    if all_brands:
        brands_names = ", ".join([b.name for b in all_brands])
    else:
        brands_names = "Бренды пока не добавлены"
    # 👆 КОНЕЦ НОВОГО БЛОКА 👆
    
    # Формируем блок текста про "Сегодня"
    if today_details:
        today_text = "\n".join(today_details)
        today_block = (
            f"📆 !!! ОТЧЕТ ЗА СЕГОДНЯ (ТЕКУЩИЕ СУТКИ) !!!:\n"
            f"{today_text}\n"
            f"(Это продажи, совершенные только сегодня. Используй эти данные, если спрашивают про сегодня)"
        )
    else:
        today_block = "📆 ОТЧЕТ ЗА СЕГОДНЯ: Продаж пока не было."

    # 5. Товары и склад
    products = await catalog_repo.get_all_products_with_stock()

    if not products:
        return "Склад пуст."

    # Собираем инфо по товарам
    total_purchase_stock = 0.0
    total_margin_stock = 0.0
    lines = []
    for p in products:
        stock_qty = sum(s.quantity for s in p.stock)
        purchase_price = float(p.purchase_price)
        sale_price = float(p.sale_price)
        margin_per_unit = sale_price - purchase_price
        if stock_qty > 0:
            total_purchase_stock += purchase_price * stock_qty
            total_margin_stock += margin_per_unit * stock_qty
        
        sold_qty = sales_map.get(p.id, 0)
        status_tag = ""
        if sold_qty > 5 and stock_qty < 2: status_tag = "[🔥 ХИТ]"
        if sold_qty == 0 and stock_qty > 5: status_tag = "[❄️ НЕЛИКВИД]"

        lines.append(
            f"ID:{p.id} | {p.title} | Остаток: {stock_qty} | Маржа/ед: {margin_per_unit:g} | Маржа склада: {margin_per_unit * stock_qty:g} | Всего продано: {sold_qty} {status_tag}"
        )

    # Собираем итоговый текст для промпта
    summary = (
        f"=== ФИНАНСОВАЯ СВОДКА ===\n"
        f"Доступные бренды: {brands_names}\n"
        f"--------------------------------\n"
        f"{today_block}\n"
        f"--------------------------------\n"
        f"🌍 ОБЩИЕ ПОКАЗАТЕЛИ (ЗА ВСЁ ВРЕМЯ РАБОТЫ):\n"
        f"Всего заказов (история): {global_stats['count']}\n"
        f"Общая выручка (история): {global_stats['revenue']:,.0f} руб.\n"
        f"Маржинальная прибыль (продажи, история): {global_stats['profit']:,.0f} руб.\n"
        f"Товарный запас: {total_purchase_stock:,.0f} руб.\n"
        f"Маржинальная прибыль склада: {total_margin_stock:,.0f} руб.\n"
        f"================================\n"
        f"ДЕТАЛИЗАЦИЯ СКЛАДА:\n"
    )
    
    return summary + "\n".join(lines)


@ai_router.message(F.text == "✨ AI-Консультант")
async def start_ai_chat(message: Message, state: FSMContext, session: AsyncSession):
    stmt = select(User).where(User.tg_id == message.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if user and normalize_role(user.role) == UserRole.STAFF.value:
        await message.answer("⛔ ИИ недоступен для продавца.")
        return

    if not settings.groq_api_key:
        await message.answer("⚠️ Система ИИ временно отключена (нет ключа).")
        return

    user_id = message.from_user.id
    is_owner = (user_id == settings.owner_id)

    if is_owner:
        await message.answer("👨‍💼 <b>Режим Владельца</b>\nСобираю финансовый отчет со склада...", parse_mode="HTML")
        context_data = await get_owner_context(session)
        system_prompt = PROMPT_OWNER
        welcome_text = (
            "📊 <b>Аналитика готова.</b>\n\n"
            "Я вижу все цены, остатки и маржу.\n"
            "Можешь спросить: <i>«Сколько денег в товаре?»</i>, <i>«Что хуже всего продается?»</i> или попросить написать пост."
        )
    else:
        await message.answer("⏳ Подключаю консультанта...")
        context_data = await get_client_context(session)
        system_prompt = PROMPT_CLIENT
        welcome_text = (
            "👋 <b>Здравствуйте! Я ваш персональный продавец-консультант.</b>\n\n"
            "Я знаю весь ассортимент и помогу подобрать размер.\n"
            "Напишите, что вы ищете (например: <i>«нужны синие брюки»</i>)."
        )

    await state.update_data(
        system_prompt_template=system_prompt,
        context_data=context_data,
        history=[] 
    )
    await state.set_state(AIStates.chatting)

    kb = InlineKeyboardBuilder()
    if not is_owner:
        kb.row(InlineKeyboardButton(text="🛍 Открыть каталог", callback_data="ai_open_catalog"))
    
    await message.answer(welcome_text, parse_mode="HTML", reply_markup=kb.as_markup())


@ai_router.callback_query(F.data.startswith("ai_cart_add:"))
async def ai_cart_add(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    product_id = int(callback.data.split(":")[1])
    repo = CatalogRepo(session)
    product = await repo.get_product_with_details(product_id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    available_sizes = [s.size for s in product.stock if s.quantity > 0]
    if not available_sizes:
        await callback.answer("Нет в наличии", show_alert=True)
        return

    await state.update_data(ai_cart_product_id=product_id)
    await state.set_state(AIStates.waiting_for_size)

    sizes_str = ", ".join(available_sizes)
    await callback.message.answer(f"Введите размер (доступно: {sizes_str}):")
    await callback.answer()


@ai_router.message(AIStates.waiting_for_size, F.text)
async def ai_cart_size_input(message: Message, state: FSMContext, session: AsyncSession):
    size_input = message.text.strip()
    if not size_input:
        await message.answer("Введите размер текстом.")
        return
    if size_input.startswith("/") or _is_exit_text(size_input):
        await state.set_state(AIStates.chatting)
        await message.answer("Вы вышли из добавления в корзину. Напишите вопрос.")
        return
    data = await state.get_data()
    product_id = data.get("ai_cart_product_id")

    if not product_id:
        await message.answer("Не удалось определить товар. Откройте карточку еще раз.")
        await state.set_state(AIStates.chatting)
        return

    repo = CatalogRepo(session)
    product = await repo.get_product_with_details(product_id)

    if not product:
        await message.answer("Товар не найден. Откройте карточку еще раз.")
        await state.set_state(AIStates.chatting)
        return

    available_stock = [s for s in product.stock if s.quantity > 0]
    match = None
    for s in available_stock:
        if s.size.lower() == size_input.lower():
            match = s
            break

    if not match:
        sizes_str = ", ".join([s.size for s in available_stock]) or "нет"
        await message.answer(f"Такого размера нет. Доступно: {sizes_str}.")
        return

    stmt = select(User).where(User.tg_id == message.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    if user is None:
        user = User(
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            role=UserRole.CLIENT.value,
            ai_quota=settings.ai_client_start_quota,
        )
        session.add(user)
        await session.commit()

    orders_repo = OrdersRepo(session)
    await orders_repo.add_to_cart(user, product, match.size, 1)
    await session.commit()

    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Вернуться в чат", callback_data="ai_back_to_chat")

    await message.answer(
        f"✅ {product.title} (размер {match.size}) добавлен в корзину!",
        reply_markup=kb.as_markup(),
    )
    await state.set_state(AIStates.chatting)


@ai_router.callback_query(F.data == "ai_back_to_chat")
async def ai_back_to_chat(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AIStates.chatting)
    await callback.message.answer("Продолжаем. Напишите вопрос.")
    await callback.answer()


@ai_router.message(AIStates.chatting, F.text)
async def process_ai_question(message: Message, state: FSMContext, session: AsyncSession):
    user_text = message.text

    if user_text.startswith("/"):
        await state.clear()
        await message.answer(
            "⚠️ <b>Вы вышли из режима ИИ.</b>\n"
            "Команды (начинающиеся с /) не работают внутри диалога.\n"
            "👇 Отправьте команду еще раз, и она сработает.",
            parse_mode="HTML"
        )
        return

    if _is_exit_text(user_text):
        await state.clear()
        await message.answer("🔌 ИИ-консультант отключен. Возвращаюсь в меню.")
        return

    user_id = message.from_user.id
    is_owner = (user_id == settings.owner_id)

    if not is_owner:
        stmt = select(User).where(User.tg_id == user_id)
        result = await session.execute(stmt)
        user_db = result.scalar_one_or_none()

        if user_db:
            if user_db.ai_quota <= 0:
                await message.answer("⚠️ Лимит сообщений исчерпан. Оформите заказ, чтобы получить новые баллы!")
                await state.clear()
                return
            user_db.ai_quota -= 1
            await session.commit()
    
    data = await state.get_data()
    prompt_template = data.get("system_prompt_template", PROMPT_CLIENT)
    context_data = data.get("context_data", "")
    history = data.get("history", [])

    if len(history) > 6: history = history[-6:]

    full_system_prompt = prompt_template.format(context_data=context_data)
    messages_payload = [{"role": "system", "content": full_system_prompt}] + history + [{"role": "user", "content": user_text}]

    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    try:
        async with aiohttp.ClientSession() as http_session:
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": messages_payload,
                "temperature": 0.5, 
                "max_tokens": 800
            }
            headers = {"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"}
            
            async with http_session.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    ai_answer = result["choices"][0]["message"]["content"]
                    
                    clean_answer = re.sub(r"\[SHOW_ID:\s*\d+\]", "", ai_answer).strip()
                    
                    if clean_answer:
                        kb = None
                        if is_owner and _is_post_request(user_text):
                            await state.update_data(pending_post=clean_answer)
                            builder = InlineKeyboardBuilder()
                            builder.button(text="📢 Разослать клиентам", callback_data="ai_broadcast_start")
                            kb = builder.as_markup()

                        await send_safe_html(message, clean_answer, reply_markup=kb)

                    found_ids = re.findall(r"\[SHOW_ID:\s*(\d+)\]", ai_answer)
                    if found_ids:
                        unique_ids = list(dict.fromkeys(found_ids))[:3]
                        for prod_id_str in unique_ids:
                            await send_product_card(
                                chat_id=message.chat.id,
                                bot=message.bot,
                                product_id=int(prod_id_str),
                                session=session,
                                is_ai_mode=True
                            )
                            await asyncio.sleep(0.3)

                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": ai_answer})
                    await state.update_data(history=history)

                else:
                    await message.answer("😴 ИИ задумался. Попробуйте другой вопрос.")
                    
    except Exception as e:
        logger.error(f"AI Handler Exception: {e}")
        await message.answer("⚠️ Техническая заминка.")


@ai_router.callback_query(F.data == "ai_broadcast_start")
async def process_ai_broadcast(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Рассылает последний ответ ИИ всем пользователям."""
    
    bot = callback.bot
    if not bot:
        await callback.answer("⚠️ Ошибка: бот не обнаружен.")
        return

    data = await state.get_data()
    post_text = data.get("pending_post")

    if not post_text:
        await callback.answer("⚠️ Текст поста потерян. Сгенерируйте новый.", show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    status_msg = await callback.message.answer("⏳ Начинаю рассылку...")

    stmt = select(User.tg_id).where(User.tg_id != settings.owner_id)
    result = await session.execute(stmt)
    user_ids = result.scalars().all()
    staff_stmt = select(User.tg_id).where(User.role == UserRole.STAFF.value)
    staff_res = await session.execute(staff_stmt)
    staff_ids = staff_res.scalars().all()
    notify_ids = list(dict.fromkeys([*user_ids, *staff_ids]))

    sent_count = 0
    
    for user_id in notify_ids:
        try:
            try:
                await bot.send_message(chat_id=user_id, text=post_text, parse_mode="HTML")
            except Exception:
                clean_text = re.sub(r"<[^>]+>", "", post_text)
                await bot.send_message(chat_id=user_id, text=clean_text)
            
            sent_count += 1
            await asyncio.sleep(0.05) 
        except Exception:
            continue

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n"
        f"📨 Доставлено: {sent_count} из {len(user_ids)} пользователей.",
        parse_mode="HTML"
    )
    await callback.answer()