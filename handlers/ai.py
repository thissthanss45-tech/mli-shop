from __future__ import annotations

import logging
import re
import asyncio
import uuid
import aiohttp
from datetime import datetime, timedelta
from io import BytesIO

from aiogram import Router, F, Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from redis.asyncio import Redis

from config import settings
from database.catalog_repo import CatalogRepo
from database.orders_repo import OrdersRepo
from models import Product, User, UserRole, Order, OrderItem, OrderStatus, StockMovement, MovementDirection, MovementOperation, TenantMembership
from utils.mq import send_task_to_queue
from utils.tenants import (
    get_or_create_default_tenant_user,
    get_primary_owner_tg_id,
    get_runtime_tenant,
    get_runtime_tenant_role_for_tg_id,
    is_runtime_owner,
    is_runtime_owner_or_staff,
    list_tenant_recipient_ids,
)

ai_router = Router()

logger = logging.getLogger(__name__)

redis_cache: Redis | None = None
CLIENT_CONTEXT_CACHE_KEY = "ai:context:client"
OWNER_CONTEXT_CACHE_KEY = "ai:context:owner"
CONTEXT_CACHE_TTL = 300  # seconds
AI_PROVIDER_KEY = "ai:provider"
AI_MODEL_KEY = "ai:model"
AI_COOLDOWN_KEY_PREFIX = "ai:cooldown"
AI_RATE_KEY_PREFIX = "ai:rate"
GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_STT_MODEL = "whisper-large-v3-turbo"

class AIStates(StatesGroup):
    chatting = State()
    waiting_for_size = State()
    waiting_for_quantity = State()
    waiting_for_order_name = State()
    waiting_for_order_phone = State()


def _is_exit_text(text: str) -> bool:
    return text in {
        "Отмена",
        "🔙 Отмена",
        "↩️ Отмена",
        "⬅ Назад",
        "🔙 Назад",
        "↩️ Назад",
        "🛍 Каталог",
        "📦 Каталог",
        "📦 Мои заказы",
        "📦 Заказы",
        "✅ История покупок",
        "🚚 Заказы в пути",
        "✨ AI-Консультант",
        "🛒 Корзина",
        "💬 Продавец",
        "💬 Владелец",
        "💬 Поддержка",
        "✍️ Написать",
        "🏠 Меню",
        "📊 Склад",
        "📋 Заказы",
        "📦 Товары",
        "📈 Статистика",
        "🏪 Витрина",
        "🛍 Перейти к покупкам",
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


def _is_checkout_request(text: str) -> bool:
    lowered = (text or "").lower()
    return (
        ("оформ" in lowered and "заказ" in lowered)
        or "хочу заказать" in lowered
        or "сделай заказ" in lowered
        or "подтвердить заказ" in lowered
    )


def _has_configured_ai_key(value: str | None) -> bool:
    normalized = (value or "").strip()
    return bool(normalized and normalized.lower() != "disabled-placeholder")


def _get_available_ai_providers() -> list[str]:
    providers: list[str] = []
    if _has_configured_ai_key(settings.deepseek_api_key):
        providers.append("deepseek")
    if _has_configured_ai_key(settings.groq_api_key):
        providers.append("groq")
    return providers


def _get_redis_cache() -> Redis | None:
    """Lazy Redis initialization shared by caching helpers."""
    global redis_cache
    if redis_cache is None:
        try:
            redis_cache = Redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        except Exception as exc:
            logger.error("Redis init failed: %s", exc)
            redis_cache = None
    return redis_cache


async def _get_cached_context(cache_key: str) -> str | None:
    cache = _get_redis_cache()
    if not cache:
        return None
    try:
        return await cache.get(cache_key)
    except Exception as exc:
        logger.error("Redis get failed for %s: %s", cache_key, exc)
        return None


async def _set_cached_context(cache_key: str, value: str) -> None:
    cache = _get_redis_cache()
    if not cache:
        return
    try:
        await cache.set(cache_key, value, ex=CONTEXT_CACHE_TTL)
    except Exception as exc:
        logger.error("Redis set failed for %s: %s", cache_key, exc)


def _tenant_cache_key(base_key: str, tenant_id: int) -> str:
    return f"{base_key}:{tenant_id}"


async def _get_catalog_repo(session: AsyncSession) -> CatalogRepo:
    tenant = await get_runtime_tenant(session)
    return CatalogRepo(session, tenant_id=tenant.id)


async def _get_orders_repo(session: AsyncSession) -> OrdersRepo:
    tenant = await get_runtime_tenant(session)
    return OrdersRepo(session, tenant_id=tenant.id)


async def _get_ai_provider() -> str:
    provider = settings.ai_provider or "groq"
    cache = _get_redis_cache()
    if cache:
        try:
            cached = await cache.get(AI_PROVIDER_KEY)
            if cached:
                provider = cached
        except Exception as exc:
            logger.error("Redis get failed for %s: %s", AI_PROVIDER_KEY, exc)
    return provider.lower()


async def _set_ai_provider(provider: str) -> bool:
    cache = _get_redis_cache()
    if not cache:
        return False
    try:
        await cache.set(AI_PROVIDER_KEY, provider)
        await cache.delete(AI_MODEL_KEY)
        return True
    except Exception as exc:
        logger.error("Redis set failed for %s: %s", AI_PROVIDER_KEY, exc)
        return False


def _build_provider_kb(providers: list[str] | None = None) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    enabled = providers or _get_available_ai_providers()
    provider_rows = [
        ("deepseek", "🐋 DeepSeek"),
        ("groq", "🦙 Llama"),
    ]
    for provider_key, provider_label in provider_rows:
        if provider_key in enabled:
            kb.button(text=provider_label, callback_data=f"ai_provider:{provider_key}")
        else:
            kb.button(text=f"{provider_label} · недоступен", callback_data=f"ai_provider_unavailable:{provider_key}")
    kb.adjust(2)
    return kb


def _ai_trigger_texts() -> set[str]:
    values = {
        "✨ AI-Консультант",
        "🌸 AI-Флорист",
        str(settings.button_ai or "").strip(),
    }
    return {value for value in values if value}


async def _acquire_ai_cooldown(user_id: int, seconds: int) -> bool:
    if seconds <= 0:
        return True
    cache = _get_redis_cache()
    if not cache:
        return True
    key = f"{AI_COOLDOWN_KEY_PREFIX}:{user_id}"
    try:
        acquired = await cache.set(key, "1", ex=seconds, nx=True)
        return bool(acquired)
    except Exception as exc:
        logger.warning("Redis cooldown set failed for %s: %s", key, exc)
        return True


async def _acquire_ai_rate_limit(user_id: int, max_requests: int, window_seconds: int) -> tuple[bool, int]:
    if max_requests <= 0 or window_seconds <= 0:
        return True, 0

    cache = _get_redis_cache()
    if not cache:
        return True, 0

    key = f"{AI_RATE_KEY_PREFIX}:{user_id}"
    now_ms = int(datetime.utcnow().timestamp() * 1000)
    window_ms = window_seconds * 1000
    cutoff_ms = now_ms - window_ms
    member = f"{now_ms}:{uuid.uuid4().hex[:8]}"

    try:
        async with cache.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(key, 0, cutoff_ms)
            pipe.zcard(key)
            result = await pipe.execute()

        current_count = int(result[1] or 0)
        if current_count >= max_requests:
            oldest = await cache.zrange(key, 0, 0, withscores=True)
            retry_after_sec = window_seconds
            if oldest:
                oldest_score = int(oldest[0][1])
                retry_after_sec = max(1, int((oldest_score + window_ms - now_ms + 999) / 1000))
            return False, retry_after_sec

        async with cache.pipeline(transaction=True) as pipe:
            pipe.zadd(key, {member: now_ms})
            pipe.expire(key, window_seconds + 5)
            await pipe.execute()

        return True, 0
    except Exception as exc:
        logger.warning("Redis rate-limit failed for %s: %s", key, exc)
        return True, 0


async def _delete_callback_message(callback: CallbackQuery) -> None:
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass


async def _start_ai_session(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user_id: int,
) -> None:
    is_owner = await is_runtime_owner(session, user_id)

    if is_owner:
        await message.answer(
            "👨‍💼 <b>Режим Владельца</b>\nСобираю финансовый отчет со склада...",
            parse_mode="HTML",
        )
        context_data = await get_owner_context(session)
        system_prompt = PROMPT_OWNER
        welcome_text = (
            "📊 <b>Аналитика готова.</b>\n\n"
            "Я вижу все цены, остатки и маржу.\n"
            "Можешь спросить: <i>«Сколько денег в товаре?»</i>, <i>«Что хуже всего продается?»</i> или попросить написать пост.\n"
            "🎙 Можно писать голосом — я отвечу текстом."
        )
    else:
        await message.answer("⏳ Подключаю консультанта...")
        context_data = await get_client_context(session)
        system_prompt = PROMPT_CLIENT
        welcome_text = (
            "👋 <b>Здравствуйте! Я ваш персональный продавец-консультант.</b>\n\n"
            "Я знаю весь ассортимент и помогу подобрать размер.\n"
            "Напишите, что вы ищете (например: <i>«нужны синие брюки»</i>).\n"
            "🎙 Можно отправить голосовое — я отвечу текстом."
        )

    await state.update_data(
        system_prompt_template=system_prompt,
        context_data=context_data,
        history=[],
    )
    await state.set_state(AIStates.chatting)

    kb = InlineKeyboardBuilder()
    if not is_owner:
        kb.row(InlineKeyboardButton(text="🛍 Открыть каталог", callback_data="ai_open_catalog"))

    await message.answer(welcome_text, parse_mode="HTML", reply_markup=kb.as_markup())


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)

PROMPT_CLIENT = """
Твоя роль: Элитный продавец-консультант бутика.
Твоя цель: Вежливо помочь клиенту выбрать товар, подобрать размер и продать.
Тон: Уважительный, услужливый, краткий.

ИНСТРУКЦИИ:
1. Используй контекст ниже ("НАШ АССОРТИМЕНТ"), чтобы отвечать на вопросы о наличии.
2. Если товара нет в списке — извинись и предложи посмотреть каталог.
3. Если клиент просит показать товар, найди его ID и вставь тег [SHOW_ID: 123].
4. Не показывай закупочные цены! Клиент видит только цену продажи.
5. Никогда не предлагай скидки, акции, бонусы или купоны. Если клиент просит скидку — вежливо откажись и предложи выбрать товар по бюджету.
5. ВАЖНО: При написании постов (маркетинговых текстов) НИКОГДА не упоминай закупочные цены, прибыль или выручку! Клиенты не должны видеть внутреннюю кухню.
6. Если вопрос клиента связан с корзиной, отвечай в первую очередь по блоку "КОРЗИНА ТЕКУЩЕГО КЛИЕНТА".
7. Не выдумывай позиции в корзине: используй только фактические товары из блока корзины.

НАШ АССОРТИМЕНТ:
{context_data}
"""


async def get_user_cart_context(session: AsyncSession, user: User | None) -> str:
    if user is None:
        return "Пользователь не найден, корзина недоступна."

    orders_repo = OrdersRepo(session)
    cart_items = await orders_repo.list_cart_items(user)
    if not cart_items:
        return "Корзина пуста."

    total = await orders_repo.get_cart_total(user)
    lines = []
    for item in cart_items:
        product = item.product
        if not product:
            continue
        brand_name = product.brand.name if product.brand else "Без бренда"
        line_total = float(item.price_at_add) * int(item.quantity)
        lines.append(
            f"• {product.title} ({brand_name}) | ID: {product.id} | Размер: {item.size} | Кол-во: {item.quantity} | Цена: {float(item.price_at_add):,.0f}₽ | Сумма: {line_total:,.0f}₽"
        )

    if not lines:
        return "Корзина пуста."

    lines.append(f"Итого по корзине: {total:,.0f}₽")
    return "\n".join(lines)

PROMPT_OWNER = """
Твоя роль: Опытный бизнес-аналитик и SMM-менеджер бутика.

ТВОИ РЕЖИМЫ РАБОТЫ:
1. 📊 АНАЛИТИКА (Если спрашивают про деньги/склад/заказы):
   - Будь жестким и точным. Используй цифры, ID, остатки, закупочные цены.
   - Указывай на "мертвый груз" (много остатка, 0 продаж).
   - Советуй закупки.
   - Отвечай на вопросы о текущих заказах, их статусе, клиентах.

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
6. Ты видишь закупочные цены и текущие заказы — используй эту информацию для анализа и ответов.
7. Для вопросов про размеры используй только поле "Остатки по размерам" из контекста. Не придумывай размеры и количество.
8. Для выручки/прибыли/количества продаж используй только точные цифры из отчета. Никаких оценок, процентов "на глаз" и предположений.
9. Всегда учитывай три сущности одновременно: Закуплено, Продано, Остаток. Если данных нет — явно напиши "нет данных".
10. Для анализа продаж по размерам используй только поле "Продано по размерам".

ФИНАНСОВЫЙ И СКЛАДСКОЙ ОТЧЕТ:
{context_data}
"""

async def get_client_context(session: AsyncSession) -> str:
    tenant = await get_runtime_tenant(session)
    cache_key = _tenant_cache_key(CLIENT_CONTEXT_CACHE_KEY, tenant.id)

    # Cache heavy context for 5 minutes to avoid hammering the DB under load.
    cached = await _get_cached_context(cache_key)
    if cached:
        return cached

    repo = CatalogRepo(session, tenant_id=tenant.id)
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
    
    context_text = "\n".join(lines) if lines else "Каталог пуст."
    await _set_cached_context(cache_key, context_text)
    return context_text


async def get_owner_context(session: AsyncSession) -> str:
    tenant = await get_runtime_tenant(session)
    cache_key = _tenant_cache_key(OWNER_CONTEXT_CACHE_KEY, tenant.id)

    # Owner analytics is even heavier, so we reuse the same 5-minute cache window.
    # cached = await _get_cached_context(cache_key)
    # if cached:
    #     return cached

    catalog_repo = CatalogRepo(session, tenant_id=tenant.id)
    orders_repo = OrdersRepo(session, tenant_id=tenant.id)

    # 1. Общие продажи (за всё время) для анализа неликвида
    sales_map = await orders_repo.get_sales_summary_by_product()

    # 1.1. Закупки (manual_add, IN) по товарам за всё время
    proc_stmt = (
        select(
            StockMovement.product_id,
            func.coalesce(func.sum(StockMovement.quantity), 0).label("procured_qty"),
        )
        .where(
            StockMovement.tenant_id == tenant.id,
            StockMovement.direction == MovementDirection.IN.value,
            StockMovement.operation_type == MovementOperation.MANUAL_ADD.value,
        )
        .group_by(StockMovement.product_id)
    )
    proc_rows = (await session.execute(proc_stmt)).all()
    procured_map = {int(row.product_id): int(row.procured_qty or 0) for row in proc_rows}

    # 1.2. Продажи по размерам (completed orders)
    sold_sizes_stmt = (
        select(
            OrderItem.product_id,
            OrderItem.size,
            func.coalesce(func.sum(OrderItem.quantity), 0).label("sold_qty"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.tenant_id == tenant.id,
            OrderItem.tenant_id == tenant.id,
            Order.status == OrderStatus.COMPLETED.value,
        )
        .group_by(OrderItem.product_id, OrderItem.size)
    )
    sold_sizes_rows = (await session.execute(sold_sizes_stmt)).all()
    sold_sizes_map: dict[int, list[tuple[str, int]]] = {}
    for row in sold_sizes_rows:
        product_id = int(row.product_id)
        size = str(row.size)
        qty = int(row.sold_qty or 0)
        sold_sizes_map.setdefault(product_id, []).append((size, qty))
    
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
    
    # 👇 НОВОЕ: ТЕКУЩИЕ ЗАКАЗЫ 👇
    current_orders = await orders_repo.get_orders_with_items_by_statuses([OrderStatus.NEW.value, OrderStatus.PROCESSING.value])
    if current_orders:
        orders_lines = []
        for order in current_orders:
            items_text = "; ".join([f"{item.product.title} (закупка: {item.product.purchase_price:g} руб., продажа: {item.sale_price:g} руб., размер: {item.size}, кол-во: {item.quantity})" for item in order.items])
            orders_lines.append(
                f"Заказ ID:{order.id} | Клиент: {order.full_name} ({order.phone}) | Сумма: {order.total_price} руб. | Статус: {order.status} | Товары: {items_text}"
            )
        current_orders_block = (
            f"📋 ТЕКУЩИЕ ЗАКАЗЫ (НОВЫЕ И В ОБРАБОТКЕ):\n" +
            "\n".join(orders_lines) +
            f"\n(Всего текущих заказов: {len(current_orders)})"
        )
    else:
        current_orders_block = "📋 ТЕКУЩИЕ ЗАКАЗЫ: Нет активных заказов."
    # 👆 КОНЕЦ БЛОКА ТЕКУЩИХ ЗАКАЗОВ 👆
    
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
    total_procured_qty = 0
    total_sold_qty = 0
    for p in products:
        stock_qty = sum(s.quantity for s in p.stock)
        size_stock = ", ".join([f"{s.size}:{s.quantity}" for s in p.stock]) if p.stock else "нет данных"
        purchase_price = float(p.purchase_price)
        sale_price = float(p.sale_price)
        margin_per_unit = sale_price - purchase_price
        if stock_qty > 0:
            total_purchase_stock += purchase_price * stock_qty
            total_margin_stock += margin_per_unit * stock_qty
        
        sold_qty = int(sales_map.get(p.id, 0) or 0)
        procured_qty = int(procured_map.get(p.id, 0) or 0)
        total_sold_qty += sold_qty
        total_procured_qty += procured_qty

        sold_sizes = sold_sizes_map.get(p.id, [])
        sold_sizes.sort(key=lambda item: (-item[1], item[0]))
        sold_sizes_text = ", ".join([f"{size}:{qty}" for size, qty in sold_sizes]) if sold_sizes else "нет данных"

        status_tag = ""
        if sold_qty > 5 and stock_qty < 2: status_tag = "[🔥 ХИТ]"
        if sold_qty == 0 and stock_qty > 5: status_tag = "[❄️ НЕЛИКВИД]"

        lines.append(
            f"ID:{p.id} | {p.title} | Бренд: {p.brand.name if p.brand else 'Без бренда'} | Фото: {len(p.photos)} шт. | Закупка: {purchase_price:g} руб. | Продажа: {sale_price:g} руб. | Закуплено всего: {procured_qty} | Остаток: {stock_qty} | Остатки по размерам: {size_stock} | Всего продано: {sold_qty} | Продано по размерам: {sold_sizes_text} | Маржа/ед: {margin_per_unit:g} | Маржа склада: {margin_per_unit * stock_qty:g} {status_tag}"
        )

    # Собираем итоговый текст для промпта
    summary = (
        f"=== ФИНАНСОВАЯ СВОДКА ===\n"
        f"Доступные бренды: {brands_names}\n"
        f"--------------------------------\n"
        f"{today_block}\n"
        f"--------------------------------\n"
        f"{current_orders_block}\n"
        f"--------------------------------\n"
        f"🌍 ОБЩИЕ ПОКАЗАТЕЛИ (ЗА ВСЁ ВРЕМЯ РАБОТЫ):\n"
        f"Всего заказов (история): {global_stats['count']}\n"
        f"Общая выручка (история): {global_stats['revenue']:,.0f} руб.\n"
        f"Маржинальная прибыль (продажи, история): {global_stats['profit']:,.0f} руб.\n"
        f"Закуплено единиц (история): {total_procured_qty}\n"
        f"Продано единиц (история): {total_sold_qty}\n"
        f"Товарный запас: {total_purchase_stock:,.0f} руб.\n"
        f"Маржинальная прибыль склада: {total_margin_stock:,.0f} руб.\n"
        f"================================\n"
        f"ДЕТАЛИЗАЦИЯ СКЛАДА:\n"
    )
    
    context_text = summary + "\n".join(lines)
    # await _set_cached_context(cache_key, context_text)
    return context_text


@ai_router.message(F.text.in_(_ai_trigger_texts()))
async def start_ai_chat(message: Message, state: FSMContext, session: AsyncSession):
    stmt = select(User).where(User.tg_id == message.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    role = await get_runtime_tenant_role_for_tg_id(session, message.from_user.id)
    if user and role == UserRole.STAFF.value:
        await message.answer("⛔ ИИ недоступен для продавца.")
        return

    user_id = message.from_user.id
    is_owner = role == UserRole.OWNER.value
    available_providers = _get_available_ai_providers()

    if not available_providers:
        await message.answer("⚠️ Система ИИ временно отключена (нет рабочего ключа).")
        return

    if is_owner:
        kb = _build_provider_kb(available_providers)
        await message.answer("Выберите AI провайдера:", reply_markup=kb.as_markup())
        return

    provider = await _get_ai_provider()
    required_key = settings.deepseek_api_key if provider == "deepseek" else settings.groq_api_key
    if not _has_configured_ai_key(required_key):
        await message.answer("⚠️ Система ИИ временно отключена (нет ключа).")
        return

    await _start_ai_session(message, state, session, user_id)


@ai_router.callback_query(F.data.startswith("ai_provider:"))
async def ai_provider_selected(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    user_id = callback.from_user.id
    if not await is_runtime_owner(session, user_id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    provider = callback.data.split(":", 1)[1].strip().lower()
    available_providers = _get_available_ai_providers()
    if provider not in {"groq", "deepseek"}:
        await callback.answer("Неизвестный провайдер", show_alert=True)
        return
    if provider not in available_providers:
        await callback.answer("Этот провайдер сейчас недоступен", show_alert=True)
        return

    saved = await _set_ai_provider(provider)
    if not saved:
        await callback.answer("Redis недоступен", show_alert=True)
        return

    required_key = settings.deepseek_api_key if provider == "deepseek" else settings.groq_api_key
    if not _has_configured_ai_key(required_key):
        await _delete_callback_message(callback)
        await callback.message.answer("⚠️ Система ИИ временно отключена (нет ключа).")
        await callback.answer()
        return

    await _delete_callback_message(callback)
    await callback.message.answer(f"✅ Провайдер выбран: <b>{provider}</b>", parse_mode="HTML")
    await _start_ai_session(callback.message, state, session, user_id)
    await callback.answer()


@ai_router.callback_query(F.data.startswith("ai_provider_unavailable:"))
async def ai_provider_unavailable(callback: CallbackQuery) -> None:
    provider = callback.data.split(":", 1)[1].strip().lower()
    labels = {
        "groq": "Llama (Groq)",
        "deepseek": "DeepSeek",
    }
    await callback.answer(f"{labels.get(provider, provider)} сейчас недоступен в этом магазине", show_alert=True)


@ai_router.callback_query(F.data.startswith("ai_cart_add:"))
async def ai_cart_add(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    product_id = int(callback.data.split(":")[1])
    repo = await _get_catalog_repo(session)
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

    repo = await _get_catalog_repo(session)
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

    await state.update_data(ai_cart_size=match.size)
    await state.set_state(AIStates.waiting_for_quantity)
    await message.answer(f"📦 Введите количество для размера {match.size} (доступно: {match.quantity}):")


@ai_router.message(AIStates.waiting_for_quantity, F.text)
async def ai_cart_quantity_input(message: Message, state: FSMContext, session: AsyncSession):
    quantity_text = (message.text or "").strip()
    if not quantity_text:
        await message.answer("Введите количество текстом.")
        return
    if quantity_text.startswith("/") or _is_exit_text(quantity_text):
        await state.set_state(AIStates.chatting)
        await message.answer("Вы вышли из добавления в корзину. Напишите вопрос.")
        return

    try:
        quantity = int(quantity_text)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите количество целым числом больше нуля.")
        return

    data = await state.get_data()
    product_id = data.get("ai_cart_product_id")
    selected_size = data.get("ai_cart_size")

    if not product_id or not selected_size:
        await message.answer("Не удалось определить товар или размер. Откройте карточку еще раз.")
        await state.set_state(AIStates.chatting)
        return

    repo = await _get_catalog_repo(session)
    product = await repo.get_product_with_details(product_id)

    if not product:
        await message.answer("Товар не найден. Откройте карточку еще раз.")
        await state.set_state(AIStates.chatting)
        return

    match = next((stock for stock in product.stock if stock.size.lower() == selected_size.lower() and stock.quantity > 0), None)
    if not match:
        await message.answer("Этот размер уже закончился. Откройте карточку товара ещё раз.")
        await state.set_state(AIStates.chatting)
        return

    stmt = select(User).where(User.tg_id == message.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    if user is None:
        user, _ = await get_or_create_default_tenant_user(
            session,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            default_role=UserRole.CLIENT.value,
            ai_quota=settings.ai_client_start_quota,
        )
        await session.commit()

    orders_repo = OrdersRepo(session, tenant_id=user.tenant_id)
    cart_items = await orders_repo.list_cart_items(user)
    existing_qty = next(
        (
            item.quantity
            for item in cart_items
            if item.product_id == product.id and item.size.lower() == selected_size.lower()
        ),
        0,
    )
    if existing_qty + quantity > match.quantity:
        available_to_add = match.quantity - existing_qty
        if available_to_add <= 0:
            await message.answer(f"В корзине уже максимум для размера {selected_size}: {existing_qty} шт.")
        else:
            await message.answer(
                f"Нельзя добавить {quantity} шт. Для размера {selected_size} доступно только {available_to_add} шт с учетом корзины."
            )
        return

    await orders_repo.add_to_cart(user, product, selected_size, quantity)
    await session.commit()

    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Вернуться в чат", callback_data="ai_back_to_chat")
    kb.button(text="🧾 Оформить заказ", callback_data="ai_checkout_start")
    kb.adjust(1)

    await message.answer(
        f"✅ {product.title} (размер {selected_size}, количество {quantity}) добавлен в корзину!",
        reply_markup=kb.as_markup(),
    )
    await state.set_state(AIStates.chatting)


@ai_router.callback_query(F.data == "ai_back_to_chat")
async def ai_back_to_chat(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AIStates.chatting)
    await callback.message.answer("Продолжаем. Напишите вопрос.")
    await callback.answer()


async def _start_ai_checkout(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user_id: int | None = None,
    username: str | None = None,
    first_name: str | None = None,
) -> bool:
    actor_user_id = user_id if user_id is not None else message.from_user.id
    actor_username = username if username is not None else message.from_user.username
    actor_first_name = first_name if first_name is not None else message.from_user.first_name

    stmt = select(User).where(User.tg_id == actor_user_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if user is None:
        user, _ = await get_or_create_default_tenant_user(
            session,
            tg_id=actor_user_id,
            username=actor_username,
            first_name=actor_first_name,
            last_name=None,
            default_role=UserRole.CLIENT.value,
            ai_quota=settings.ai_client_start_quota,
        )
        await session.commit()

    orders_repo = OrdersRepo(session, tenant_id=user.tenant_id)
    cart_items = await orders_repo.list_cart_items(user)
    if not cart_items:
        await message.answer("🛒 Корзина пуста. Добавьте товары и затем оформите заказ.")
        return False

    await state.set_state(AIStates.waiting_for_order_name)
    await message.answer("📝 Отлично, оформляем заказ. Как к вам обращаться? (Введите имя)")
    return True


@ai_router.callback_query(F.data == "ai_checkout_start")
async def ai_checkout_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    await _start_ai_checkout(
        callback.message,
        state,
        session,
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
    )
    await callback.answer()


@ai_router.message(AIStates.waiting_for_order_name, F.text)
async def ai_checkout_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name or _is_exit_text(name):
        await state.set_state(AIStates.chatting)
        await message.answer("↩️ Оформление заказа отменено. Продолжаем чат.")
        return

    await state.update_data(ai_order_full_name=name)
    await state.set_state(AIStates.waiting_for_order_phone)
    await message.answer("📱 Введите контактный телефон:")


@ai_router.message(AIStates.waiting_for_order_phone, F.text)
async def ai_checkout_phone(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    phone = (message.text or "").strip()
    if _is_exit_text(phone):
        await state.set_state(AIStates.chatting)
        await message.answer("↩️ Оформление заказа отменено. Продолжаем чат.")
        return

    digits = re.sub(r"\D", "", phone)
    if len(digits) < 7:
        await message.answer("Введите корректный телефон (минимум 7 цифр).")
        return

    data = await state.get_data()
    full_name = (data.get("ai_order_full_name") or "").strip()
    if not full_name:
        await state.set_state(AIStates.waiting_for_order_name)
        await message.answer("Не вижу имя. Повторите, пожалуйста, как к вам обращаться.")
        return

    stmt = select(User).where(User.tg_id == message.from_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if user is None:
        user, _ = await get_or_create_default_tenant_user(
            session,
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            default_role=UserRole.CLIENT.value,
            ai_quota=settings.ai_client_start_quota,
        )
        await session.commit()

    orders_repo = OrdersRepo(session, tenant_id=user.tenant_id)
    cart_items = await orders_repo.list_cart_items(user)
    if not cart_items:
        await message.answer("🛒 Корзина пуста. Добавьте товары и попробуйте снова.")
        await state.set_state(AIStates.chatting)
        return

    order = await orders_repo.create_order(
        user=user,
        full_name=full_name,
        phone=phone,
        address="Не указан (оформлено через AI)",
        cart_items=cart_items,
    )

    if order is None:
        await message.answer(
            "⚠️ Пока оформляли заказ, один из товаров закончился. Проверьте корзину и попробуйте снова.",
            parse_mode="HTML",
        )
        await state.set_state(AIStates.chatting)
        return

    user.ai_quota += settings.ai_client_bonus_quota
    user.ai_bonus_at = datetime.utcnow()
    await orders_repo.clear_cart(user)
    await session.commit()

    await message.answer(
        f"✅ <b>Заказ #{order.id} оформлен!</b>\n"
        f"Менеджер свяжется с вами.\n"
        f"🎁 Начислено {settings.ai_client_bonus_quota} AI-запросов.",
        parse_mode="HTML",
    )

    items_list_text = ""
    for it in cart_items:
        brand = it.product.brand.name if (it.product and it.product.brand) else ""
        title = it.product.title if it.product else "???"
        sku = it.product.sku if (it.product and it.product.sku) else None
        sku_part = f" [{sku}]" if sku else ""
        items_list_text += f"— {brand} {title}{sku_part} ({it.size}) x{it.quantity}\n"

    try:
        admin_text = (
            f"🔔 <b>НОВЫЙ ЗАКАЗ #{order.id}</b>\n"
            f"👤 Клиент: {full_name} (@{message.from_user.username})\n"
            f"📱 Телефон: {phone}\n"
            f"💰 Сумма: {order.total_price} ₽\n\n"
            f"📦 <b>Состав заказа:</b>\n"
            f"{items_list_text}"
        )
        owner_tg_id = await get_primary_owner_tg_id(session, order.tenant_id or 0)
        recipients = await list_tenant_recipient_ids(session, order.tenant_id or 0)
        if owner_tg_id:
            await bot.send_message(owner_tg_id, admin_text, parse_mode="HTML")
        for staff_id in recipients:
            if staff_id in {owner_tg_id, message.from_user.id}:
                continue
            try:
                await bot.send_message(staff_id, admin_text, parse_mode="HTML")
            except Exception:
                continue
    except Exception as exc:
        logger.error("AI checkout notify failed: %s", exc)

    await state.set_state(AIStates.chatting)
    await message.answer("✨ Заказ готов. Могу помочь с новым выбором или ответить по каталогу.")


async def _broadcast_post(bot: Bot, user_ids: list[int], post_text: str) -> int:
    """High-throughput broadcaster that fan-outs text via worker pool."""
    if not user_ids:
        return 0

    queue: asyncio.Queue[int] = asyncio.Queue()
    # Feed IDs into the queue to let multiple workers fan-out concurrently.
    for uid in user_ids:
        queue.put_nowait(uid)

    worker_count = min(32, len(user_ids)) or 1
    plain_text = _strip_html(post_text)
    sent_count = 0
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal sent_count
        while True:
            user_id = await queue.get()
            delivered = False
            try:
                await bot.send_message(chat_id=user_id, text=post_text, parse_mode="HTML")
                delivered = True
            except TelegramBadRequest as exc:
                logger.warning(
                    "Broadcast HTML failed for %s: %s. Falling back to plain text.",
                    user_id,
                    exc,
                )
                try:
                    await bot.send_message(chat_id=user_id, text=plain_text)
                    delivered = True
                except Exception as inner_exc:
                    logger.error("Plain broadcast failed for %s: %s", user_id, inner_exc)
            except (TelegramForbiddenError, TelegramNotFound) as exc:
                logger.info("Broadcast skipped for %s: %s", user_id, exc)
            except Exception as exc:
                logger.error("Broadcast error for %s: %s", user_id, exc)
            finally:
                if delivered:
                    async with lock:
                        sent_count += 1
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
    await queue.join()
    for task in workers:
        task.cancel()
    return sent_count


async def _transcribe_voice_message(message: Message) -> str | None:
    if not message.voice:
        return None

    if not settings.groq_api_key:
        await message.answer("⚠️ Голосовой ввод временно недоступен: не настроен GROQ_API_KEY.")
        return None

    try:
        file_info = await message.bot.get_file(message.voice.file_id)
        file_url = f"https://api.telegram.org/file/bot{settings.bot_token}/{file_info.file_path}"

        timeout = aiohttp.ClientTimeout(total=max(15, settings.ai_request_timeout_sec))
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.get(file_url) as resp:
                if resp.status != 200:
                    logger.error("Voice download failed status=%s", resp.status)
                    await message.answer("⚠️ Не удалось скачать голосовое сообщение.")
                    return None
                audio_bytes = await resp.read()

            form = aiohttp.FormData()
            form.add_field("model", GROQ_STT_MODEL)
            form.add_field(
                "file",
                BytesIO(audio_bytes),
                filename="voice.ogg",
                content_type="audio/ogg",
            )

            headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
            async with http.post(GROQ_STT_URL, headers=headers, data=form) as stt_resp:
                if stt_resp.status != 200:
                    error_text = await stt_resp.text()
                    logger.error("Groq STT failed status=%s body=%s", stt_resp.status, error_text[:400])
                    await message.answer("⚠️ Не удалось распознать голосовое. Попробуйте еще раз.")
                    return None

                payload = await stt_resp.json()
                transcript = str(payload.get("text") or "").strip()
                if not transcript:
                    await message.answer("⚠️ Не удалось распознать речь. Попробуйте записать голос четче.")
                    return None
                return transcript
    except Exception as exc:
        logger.exception("Voice transcription failed: %s", exc)
        await message.answer("⚠️ Ошибка распознавания голоса. Попробуйте отправить текстом.")
        return None


async def _process_ai_input_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user_text: str,
) -> None:
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

    if _is_checkout_request(user_text):
        await _start_ai_checkout(message, state, session)
        return

    user_id = message.from_user.id
    is_owner = await is_runtime_owner(session, user_id)
    can_broadcast_ai_posts = await is_runtime_owner_or_staff(session, user_id)
    user_db: User | None = None

    if not is_owner:
        cooldown_ok = await _acquire_ai_cooldown(user_id, settings.ai_min_interval_sec)
        if not cooldown_ok:
            await message.answer("⏱ Слишком часто. Подождите пару секунд и отправьте запрос снова.")
            return

        rate_ok, retry_after = await _acquire_ai_rate_limit(
            user_id,
            settings.ai_rate_limit_max_requests,
            settings.ai_rate_limit_window_sec,
        )
        if not rate_ok:
            await message.answer(
                f"🚦 Лимит запросов исчерпан. Попробуйте снова через ~{retry_after} сек."
            )
            return

    if not is_owner:
        stmt = select(User).where(User.tg_id == user_id)
        result = await session.execute(stmt)
        user_db = result.scalar_one_or_none()

        if user_db:
            if user_db.ai_bonus_at:
                elapsed = datetime.utcnow() - user_db.ai_bonus_at
                if elapsed >= timedelta(hours=5):
                    if user_db.ai_quota < settings.ai_client_start_quota:
                        user_db.ai_quota = settings.ai_client_start_quota
                    user_db.ai_bonus_at = None
                    await session.commit()

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

    if len(history) > 6:
        history = history[-6:]

    full_system_prompt = prompt_template.format(context_data=context_data)
    if not is_owner:
        cart_context = await get_user_cart_context(session, user_db)
        full_system_prompt += f"\n\nКОРЗИНА ТЕКУЩЕГО КЛИЕНТА:\n{cart_context}"
    messages_payload = [{"role": "system", "content": full_system_prompt}] + history + [{"role": "user", "content": user_text}]

    try:
        task_payload = {
            "chat_id": message.chat.id,
            "user_id": message.from_user.id,
            "messages": messages_payload,
            "can_broadcast_ai_posts": can_broadcast_ai_posts,
        }
        request_id = await send_task_to_queue("ai_generation", task_payload)
        history.append({"role": "user", "content": user_text})
        await state.update_data(history=history)
        logger.info("AI task queued request_id=%s chat_id=%s", request_id, message.chat.id)
        await message.answer("⏳ Запрос в очереди...")
    except Exception as exc:
        logger.error("AI queue publish failed chat_id=%s error=%s", message.chat.id, exc)
        await message.answer("⚠️ Техническая заминка.")


@ai_router.message(AIStates.chatting, F.text)
async def process_ai_question(message: Message, state: FSMContext, session: AsyncSession):
    await _process_ai_input_text(message, state, session, message.text)


@ai_router.message(AIStates.chatting, F.voice)
async def process_ai_voice_question(message: Message, state: FSMContext, session: AsyncSession):
    status = await message.answer("🎙 Распознаю голосовое сообщение...")
    transcript = await _transcribe_voice_message(message)
    if not transcript:
        return

    preview = transcript if len(transcript) <= 350 else f"{transcript[:350]}..."
    await status.edit_text(f"📝 Распознано: {preview}")
    await _process_ai_input_text(message, state, session, transcript)


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

    tenant_id = None
    actor = (await session.execute(select(User).where(User.tg_id == callback.from_user.id))).scalar_one_or_none()
    if actor is not None and actor.tenant_id is not None:
        tenant_id = actor.tenant_id
    if tenant_id is None:
        tenant = await get_runtime_tenant(session)
        tenant_id = tenant.id

    notify_ids: list[int] = []
    if tenant_id:
        user_stmt = (
            select(User.tg_id)
            .join(TenantMembership, TenantMembership.user_id == User.id)
            .where(TenantMembership.tenant_id == tenant_id, User.tg_id.is_not(None))
        )
        result = await session.execute(user_stmt)
        user_ids = [uid for uid in result.scalars().all() if uid]
        staff_ids = await list_tenant_recipient_ids(session, tenant_id)
        notify_ids = [
            uid
            for uid in dict.fromkeys([*user_ids, *staff_ids])
            if uid and uid != callback.from_user.id
        ]

    logger.info(
        "AI broadcast tenant_id=%s actor_tg_id=%s recipients=%s",
        tenant_id,
        callback.from_user.id,
        notify_ids,
    )

    if not notify_ids:
        await status_msg.edit_text("⚠️ Нет пользователей для рассылки.")
        await callback.answer()
        return

    sent_count = await _broadcast_post(bot, notify_ids, post_text)

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n"
        f"📨 Доставлено: {sent_count} из {len(notify_ids)} получателей.",
        parse_mode="HTML"
    )
    await callback.answer()