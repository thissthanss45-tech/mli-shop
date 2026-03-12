from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal

import aiohttp
import aio_pika
from aio_pika.abc import AbstractIncomingMessage
from aiogram import Bot
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import InlineKeyboardMarkup
from redis.asyncio import Redis
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from config import settings
from database.catalog_repo import CatalogRepo
from database.db_manager import async_session_maker
from models import Order, OrderItem, Product, Brand, OrderStatus, AIChatLog
from utils.admin_kb import admin_kb
from utils.cards import send_product_card
from utils.mq import send_task_to_queue
from utils.tenants import resolve_tenant_by_bot_token

QUEUE_NAME = "ai_generation"
DLQ_QUEUE_NAME = settings.ai_dlq_queue_name
MAX_HISTORY_ITEMS = 12
AI_PROVIDER_KEY = "ai:provider"
AI_MODEL_KEY = "ai:model"

logger = logging.getLogger(__name__)
redis_cache: Redis | None = None
AI_CONFIG_CACHE_TTL_SEC = 60.0
ai_config_cache_value: tuple[str, str, str, str] | None = None
ai_config_cache_expire_at: float = 0.0


def _get_redis_cache() -> Redis | None:
    global redis_cache
    if redis_cache is None:
        try:
            redis_cache = Redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        except Exception as exc:
            logger.warning("Redis cache init failed: %s", exc)
            redis_cache = None
    return redis_cache


async def _get_ai_overrides() -> tuple[str | None, str | None]:
    cache = _get_redis_cache()
    if not cache:
        return None, None
    try:
        provider = await cache.get(AI_PROVIDER_KEY)
        model = await cache.get(AI_MODEL_KEY)
        return provider, model
    except Exception as exc:
        logger.error("Redis get failed for AI overrides: %s", exc)
        return None, None


def _sanitize_html(text: str) -> str:
    safe_text = html.escape(text)
    safe_text = safe_text.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    safe_text = safe_text.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    safe_text = safe_text.replace("&lt;code&gt;", "<code>").replace("&lt;/code&gt;", "</code>")
    safe_text = safe_text.replace("&lt;pre&gt;", "<pre>").replace("&lt;/pre&gt;", "</pre>")
    return safe_text


def _split_text(text: str, max_length: int) -> list[str]:
    if len(text) <= max_length:
        return [text]

    parts: list[str] = []
    current_part = ""
    for line in text.split("\n"):
        line = line + "\n"
        while len(line) > max_length:
            if current_part:
                parts.append(current_part)
                current_part = ""
            parts.append(line[:max_length])
            line = line[max_length:]

        if len(current_part) + len(line) > max_length:
            parts.append(current_part)
            current_part = line
        else:
            current_part += line

    if current_part:
        parts.append(current_part)

    return parts


def _extract_show_ids(text: str) -> list[int]:
    ids = re.findall(r"\[SHOW_ID:\s*(\d+)\]", text)
    unique_ids: list[int] = []
    for raw_id in ids:
        value = int(raw_id)
        if value not in unique_ids:
            unique_ids.append(value)
    return unique_ids[:3]


def _strip_show_tags(text: str) -> str:
    return re.sub(r"\[SHOW_ID:\s*\d+\]", "", text).strip()


def _is_broadcast_content(text: str) -> bool:
    lowered = (text or "").lower()
    keywords = [
        "пост",
        "реклама",
        "рассылка",
        "разосл",
        "отправить",
        "клиентам",
        "поздравить",
        "поздрав",
        "праздник",
        "акция",
        "скидка",
        "анонс",
        "подборка",
        "новинк",
        "предложен",
    ]
    return any(keyword in lowered for keyword in keywords)


def _is_post_request(text: str) -> bool:
    lowered = text.lower()
    return bool(re.search(r"\b(напиши(?:те)?|сделай|создай)\s+пост\b", lowered)) or (
        "пост" in lowered and any(word in lowered for word in ["реклам", "рассыл", "smm", "промо", "пост"])
    )


def _resolve_report_period(user_text: str) -> tuple[datetime | None, datetime | None, str]:
    text = (user_text or "").lower()
    now = datetime.now()

    if "сегодня" in text or "за сегодня" in text or "текущие сутки" in text:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        return start, end, f"Today ({start.strftime('%d.%m.%Y')})"

    if "вчера" in text:
        yesterday = now - timedelta(days=1)
        start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
        return start, end, f"Yesterday ({start.strftime('%d.%m.%Y')})"

    date_match = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", text)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year_raw = date_match.group(3)
        year = now.year
        if year_raw:
            parsed_year = int(year_raw)
            year = parsed_year + 2000 if parsed_year < 100 else parsed_year

        try:
            picked = datetime(year=year, month=month, day=day)
            start = picked.replace(hour=0, minute=0, second=0, microsecond=0)
            end = picked.replace(hour=23, minute=59, second=59, microsecond=999999)
            return start, end, f"Date ({start.strftime('%d.%m.%Y')})"
        except ValueError:
            pass

    return None, None, "All time"


def _is_financial_query(user_text: str) -> bool:
    text = (user_text or "").lower()
    finance_keywords = [
        "торгов",
        "продаж",
        "продал",
        "продали",
        "выруч",
        "прибыл",
        "отчет",
        "отчёт",
        "оборот",
        "марж",
    ]
    return any(keyword in text for keyword in finance_keywords)


def _has_explicit_period(user_text: str) -> bool:
    text = (user_text or "").lower()
    if "сегодня" in text or "за сегодня" in text or "текущие сутки" in text or "вчера" in text:
        return True
    return bool(re.search(r"\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\b", text))


def _extract_recent_period_hint(messages_payload: list[dict], max_messages: int = 8) -> str | None:
    if not isinstance(messages_payload, list):
        return None

    for item in reversed(messages_payload[-max_messages:]):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").lower()
        if not content:
            continue
        if "сегодня" in content or "за сегодня" in content or "текущие сутки" in content:
            return "сегодня"
        if "вчера" in content:
            return "вчера"
        date_match = re.search(r"\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\b", content)
        if date_match:
            return date_match.group(0)
    return None


def _enrich_query_with_period(user_text: str, messages_payload: list[dict]) -> str:
    if _has_explicit_period(user_text):
        return user_text

    period_hint = _extract_recent_period_hint(messages_payload)
    if not period_hint:
        return user_text
    return f"{user_text} {period_hint}".strip()


def _wants_sales_details(user_text: str) -> bool:
    text = (user_text or "").lower()
    detail_keywords = [
        "что продали",
        "какие продажи",
        "список продаж",
        "детал",
        "по заказам",
        "перечень",
        "покажи продажи",
    ]
    return any(keyword in text for keyword in detail_keywords)


def _is_today_summary_query(user_text: str) -> bool:
    text = (user_text or "").lower()
    if "сегодня" not in text and "за сегодня" not in text and "текущие сутки" not in text:
        return False
    summary_markers = ["что у нас", "сводк", "итоги", "как дела", "продажи"]
    return any(marker in text for marker in summary_markers)


def _is_order_id_query(user_text: str) -> bool:
    text = (user_text or "").lower()
    asks_id = "id" in text and "товар" in text
    asks_order = "заказ" in text
    return asks_id and asks_order


def _extract_order_id_from_text(user_text: str) -> int | None:
    text = (user_text or "").lower()
    match = re.search(r"(?:заказ\s*#?\s*|#)(\d+)", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


async def _build_last_order_id_answer() -> str:
    async with async_session_maker() as session:
        stmt = (
            select(Order)
            .options(
                selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.brand)
            )
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(1)
        )
        order = (await session.execute(stmt)).scalar_one_or_none()

    if not order:
        return "📋 Заказов в базе пока нет."

    if not order.items:
        return f"📋 Последний заказ #{order.id} найден, но в нем нет позиций."

    lines = [
        "📋 <b>Детализация последнего заказа</b>",
        "",
        f"Последний заказ: <b>#{order.id}</b>",
    ]

    for item in order.items:
        if not item.product:
            lines.append("• Товар удален из каталога")
            continue
        brand_name = item.product.brand.name if item.product.brand else "Без бренда"
        lines.append(
            f"• <b>{item.product.title}</b> ({brand_name}) | ID товара: <code>{item.product.id}</code> | SKU: <code>{item.product.sku}</code> | Кол-во: {item.quantity}"
        )

    lines.append("")
    lines.append("ℹ️ ID товаров указан напрямую из базы данных без генерации ИИ.")
    return "\n".join(lines)


async def _build_specific_order_id_answer(order_id: int) -> str:
    async with async_session_maker() as session:
        stmt = (
            select(Order)
            .options(
                selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.brand)
            )
            .where(Order.id == order_id)
            .limit(1)
        )
        order = (await session.execute(stmt)).scalar_one_or_none()

    if not order:
        return f"📋 Заказ #{order_id} не найден."
    if not order.items:
        return f"📋 Заказ #{order.id} найден, но в нем нет позиций."

    lines = [
        f"📋 <b>Товары в заказе #{order.id}</b>",
        "",
    ]
    for item in order.items:
        if not item.product:
            lines.append("• Товар удален из каталога")
            continue
        brand_name = item.product.brand.name if item.product.brand else "Без бренда"
        lines.append(
            f"• <b>{item.product.title}</b> ({brand_name}) | ID товара: <code>{item.product.id}</code> | SKU: <code>{item.product.sku}</code> | Кол-во: {item.quantity}"
        )

    lines.append("")
    lines.append("ℹ️ ID товаров указан напрямую из базы данных без генерации ИИ.")
    return "\n".join(lines)


async def _build_all_orders_ids_answer(limit_orders: int = 30) -> str:
    async with async_session_maker() as session:
        stmt = (
            select(Order)
            .options(
                selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.brand)
            )
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(limit_orders)
        )
        orders = (await session.execute(stmt)).scalars().all()

    if not orders:
        return "📋 Заказов в базе пока нет."

    lines = ["📋 <b>ID товаров по заказам</b>", ""]
    for order in orders:
        lines.append(f"<b>Заказ #{order.id}</b>")
        if not order.items:
            lines.append("• Нет позиций")
            lines.append("")
            continue
        for item in order.items:
            if not item.product:
                lines.append("• Товар удален из каталога")
                continue
            brand_name = item.product.brand.name if item.product.brand else "Без бренда"
            lines.append(
                f"• {item.product.title} ({brand_name}) | ID: <code>{item.product.id}</code> | SKU: <code>{item.product.sku}</code> | x{item.quantity}"
            )
        lines.append("")

    lines.append(f"ℹ️ Показаны последние {len(orders)} заказов. ID указаны напрямую из БД.")
    return "\n".join(lines)


async def _build_order_ids_answer(user_text: str) -> str:
    text = (user_text or "").lower()
    explicit_order_id = _extract_order_id_from_text(text)
    if explicit_order_id is not None:
        return await _build_specific_order_id_answer(explicit_order_id)

    if "последн" in text:
        return await _build_last_order_id_answer()

    if "все" in text or "по заказам" in text:
        return await _build_all_orders_ids_answer(limit_orders=50)

    return (
        "Чтобы выдать точные ID, уточните заказ: например 'ID товара по заказу #17', "
        "или 'ID товаров по последнему заказу', или 'ID товаров по всем заказам'."
    )


def _build_factual_finance_answer(db_stats: dict) -> str:
    period_name = db_stats.get("period_name", "All time")
    revenue = Decimal(str(db_stats.get("revenue", 0))).quantize(Decimal("0.01"))
    profit = Decimal(str(db_stats.get("profit", 0))).quantize(Decimal("0.01"))
    top_items = db_stats.get("top_items_list", "none")

    return (
        f"📊 <b>Финансовый отчет</b>\n"
        f"Период: <b>{period_name}</b>\n"
        f"💰 Выручка: <b>{revenue} RUB</b>\n"
        f"📈 Чистая прибыль: <b>{profit} RUB</b>\n"
        f"🏆 Топ товаров: <b>{top_items}</b>"
    )


async def _collect_db_stats(user_text: str) -> dict:
    start_dt, end_dt, period_name = _resolve_report_period(user_text)
    conditions = [Order.status == OrderStatus.COMPLETED.value]
    if start_dt and end_dt:
        conditions.append(Order.created_at.between(start_dt, end_dt))

    async with async_session_maker() as session:
        revenue_stmt = select(func.coalesce(func.sum(Order.total_price), 0)).where(*conditions)
        revenue_value = await session.scalar(revenue_stmt)
        revenue = float(revenue_value or 0)

        profit_expr = (OrderItem.sale_price - Product.purchase_price) * OrderItem.quantity
        profit_stmt = (
            select(func.coalesce(func.sum(profit_expr), 0))
            .join(Order, Order.id == OrderItem.order_id)
            .join(Product, Product.id == OrderItem.product_id)
            .where(*conditions)
        )
        profit_value = await session.scalar(profit_stmt)
        profit = float(profit_value or 0)

        top_stmt = (
            select(Product.title, func.coalesce(func.sum(OrderItem.quantity), 0).label("qty"))
            .join(OrderItem, OrderItem.product_id == Product.id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(*conditions)
            .group_by(Product.id, Product.title)
            .order_by(func.sum(OrderItem.quantity).desc())
            .limit(5)
        )
        top_rows = (await session.execute(top_stmt)).all()

    top_items_list = ", ".join([f"{title} x{int(qty)}" for title, qty in top_rows]) if top_rows else "none"

    return {
        "period_name": period_name,
        "revenue": round(revenue, 2),
        "profit": round(profit, 2),
        "top_items_list": top_items_list,
    }


async def _collect_sales_details_for_period(start_dt: datetime | None, end_dt: datetime | None) -> dict:
    conditions = [Order.status == OrderStatus.COMPLETED.value]
    if start_dt and end_dt:
        conditions.append(Order.created_at.between(start_dt, end_dt))

    async with async_session_maker() as session:
        details_stmt = (
            select(
                Order.id.label("order_id"),
                Order.created_at,
                Product.title,
                Brand.name.label("brand"),
                OrderItem.quantity,
                OrderItem.sale_price,
                Product.purchase_price,
            )
            .join(OrderItem, Order.id == OrderItem.order_id)
            .join(Product, Product.id == OrderItem.product_id)
            .join(Brand, Brand.id == Product.brand_id)
            .where(*conditions)
            .order_by(Order.created_at.asc(), Order.id.asc())
        )
        rows = (await session.execute(details_stmt)).all()

    lines: list[str] = []
    order_ids: set[int] = set()
    for row in rows:
        order_ids.add(int(row.order_id))
        qty = int(row.quantity)
        sale_total = float(row.sale_price) * qty
        lines.append(
            f"• Заказ #{row.order_id} | {row.title} ({row.brand}) | {qty} шт | {float(row.sale_price):.2f} RUB | {sale_total:.2f} RUB"
        )

    return {
        "lines": lines,
        "orders_count": len(order_ids),
        "items_count": len(rows),
    }


def _build_factual_full_report(db_stats: dict, sales_details: dict) -> str:
    period_name = db_stats.get("period_name", "All time")
    revenue = Decimal(str(db_stats.get("revenue", 0))).quantize(Decimal("0.01"))
    profit = Decimal(str(db_stats.get("profit", 0))).quantize(Decimal("0.01"))
    top_items = db_stats.get("top_items_list", "none")
    orders_count = int(sales_details.get("orders_count", 0))
    items_count = int(sales_details.get("items_count", 0))
    lines = sales_details.get("lines", [])

    details_block = "\n".join(lines) if lines else "• Продаж за период нет"

    return (
        f"📊 <b>ПОЛНЫЙ ОТЧЕТ О ПРОДАЖАХ</b>\n"
        f"Период: <b>{period_name}</b>\n\n"
        f"<b>Детализация:</b>\n{details_block}\n\n"
        f"<b>ИТОГО:</b>\n"
        f"• Количество заказов: <b>{orders_count}</b>\n"
        f"• Количество позиций: <b>{items_count}</b>\n"
        f"• Выручка: <b>{revenue} RUB</b>\n"
        f"• Чистая прибыль: <b>{profit} RUB</b>\n"
        f"• Топ товаров: <b>{top_items}</b>\n"
        f"\nℹ️ Все цифры рассчитаны строго по базе данных без приближений."
    )


def _build_db_stats_block(db_stats: dict) -> str:
    revenue = Decimal(str(db_stats.get("revenue", 0))).quantize(Decimal("0.01"))
    profit = Decimal(str(db_stats.get("profit", 0))).quantize(Decimal("0.01"))
    return (
        "\n[CURRENT_DB_STATS]\n"
        "This block is authoritative for date-based financial answers.\n"
        "Never invent numbers, orders, or products outside this block.\n"
        "If user asks about revenue/profit/orders for a period, answer only with exact numbers from this block and do not estimate.\n"
        f"Report Period: {db_stats.get('period_name', 'All time')}\n"
        f"Revenue: {revenue} RUB\n"
        f"Net Profit: {profit} RUB\n"
        f"Top Items: {db_stats.get('top_items_list', 'none')}\n"
    )


def _inject_db_stats_into_system(messages_payload: list[dict], db_stats_block: str) -> list[dict]:
    if not isinstance(messages_payload, list):
        return messages_payload

    enriched_messages = [dict(item) if isinstance(item, dict) else item for item in messages_payload]
    for item in enriched_messages:
        if isinstance(item, dict) and item.get("role") == "system":
            original = str(item.get("content") or "")
            if "[CURRENT_DB_STATS]" not in original:
                item["content"] = f"{db_stats_block}\n{original}"
            return enriched_messages

    enriched_messages.insert(0, {"role": "system", "content": db_stats_block})
    return enriched_messages


async def _send_safe_html(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if not text:
        return

    safe_text = _sanitize_html(text)
    parts = _split_text(safe_text, max_length=4096)
    for idx, part in enumerate(parts):
        markup = reply_markup if idx == len(parts) - 1 else None
        await bot.send_message(chat_id=chat_id, text=part, parse_mode="HTML", reply_markup=markup)


def _has_configured_ai_key(value: str | None) -> bool:
    normalized = (value or "").strip()
    return bool(normalized and normalized.lower() != "disabled-placeholder")

async def _resolve_ai_config() -> tuple[str, str, str, str]:
    global ai_config_cache_value, ai_config_cache_expire_at
    now = time.monotonic()
    if ai_config_cache_value is not None and now < ai_config_cache_expire_at:
        return ai_config_cache_value

    provider_override, model_override = await _get_ai_overrides()
    provider = (provider_override or settings.ai_provider or "groq").lower()
    defaults = {
        "groq": {
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "model": settings.groq_model or "llama-3.3-70b-versatile",
            "api_key": settings.groq_api_key,
        },
        "deepseek": {
            "url": "https://api.deepseek.com/v1/chat/completions",
            "model": settings.deepseek_model or "deepseek-chat",
            "api_key": settings.deepseek_api_key,
        },
    }

    if provider not in defaults:
        raise RuntimeError(f"Unsupported AI provider: {provider}")

    data = defaults[provider]
    api_key = data["api_key"]
    if not _has_configured_ai_key(api_key):
        raise RuntimeError(f"{provider} API key is missing")

    model = (model_override or settings.ai_model or data["model"]).strip() or data["model"]
    url = data["url"]
    resolved = (provider, api_key, url, model)
    ai_config_cache_value = resolved
    ai_config_cache_expire_at = now + AI_CONFIG_CACHE_TTL_SEC
    return resolved


async def _request_ai(messages_payload: list[dict]) -> str:
    provider, api_key, url, model = await _resolve_ai_config()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages_payload,
        "temperature": 0.5,
        "max_tokens": 800,
    }

    timeout = aiohttp.ClientTimeout(total=max(5, settings.ai_request_timeout_sec))
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"{provider} API error {resp.status}: {body}")
            result = await resp.json()

    return result["choices"][0]["message"]["content"]


async def _append_history(storage: RedisStorage, bot_id: int, chat_id: int, user_id: int, ai_answer: str) -> None:
    key = StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=user_id)
    data = await storage.get_data(key)
    history = data.get("history", [])
    history.append({"role": "assistant", "content": ai_answer})
    if len(history) > MAX_HISTORY_ITEMS:
        history = history[-MAX_HISTORY_ITEMS:]
    data["history"] = history
    await storage.set_data(key, data)


async def _set_pending_post(
    storage: RedisStorage,
    bot_id: int,
    chat_id: int,
    user_id: int,
    post_text: str,
) -> None:
    key = StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=user_id)
    data = await storage.get_data(key)
    data["pending_post"] = post_text
    await storage.set_data(key, data)


async def _send_product_cards(bot: Bot, chat_id: int, product_ids: list[int]) -> None:
    if not product_ids:
        return

    async with async_session_maker() as session:
        repo = CatalogRepo(session)
        for product_id in product_ids:
            product = await repo.get_product_with_details(product_id)
            if not product:
                continue
            await send_product_card(
                chat_id=chat_id,
                bot=bot,
                product_id=product_id,
                session=session,
                is_ai_mode=True,
            )
            await asyncio.sleep(0.3)


def _get_retry_count(message: AbstractIncomingMessage) -> int:
    try:
        payload = json.loads(message.body)
        if isinstance(payload, dict) and payload.get("retry_count") is not None:
            return int(payload.get("retry_count"))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    headers = message.headers or {}
    raw = headers.get("x-retry-count", 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


async def _republish_with_retry(message: AbstractIncomingMessage, payload: dict, retry_count: int, error_text: str) -> None:
    payload["last_error"] = error_text[:500]
    payload["retry_count"] = retry_count + 1
    await send_task_to_queue(QUEUE_NAME, payload)


async def _publish_to_dlq(message: AbstractIncomingMessage, payload: dict, retry_count: int, error_text: str) -> None:
    payload["failed_at"] = datetime.utcnow().isoformat()
    payload["last_error"] = error_text[:1000]
    payload["retry_count"] = retry_count
    payload["final_error"] = error_text[:1000]
    await send_task_to_queue(DLQ_QUEUE_NAME, payload)


async def _persist_ai_chat_log(user_tg_id: int, user_text: str, assistant_text: str) -> None:
    try:
        async with async_session_maker() as session:
            tenant = await resolve_tenant_by_bot_token(session, settings.bot_token)
            session.add(
                AIChatLog(
                    tenant_id=tenant.id,
                    user_tg_id=user_tg_id,
                    role="user",
                    content=user_text or "",
                )
            )
            session.add(
                AIChatLog(
                    tenant_id=tenant.id,
                    user_tg_id=user_tg_id,
                    role="assistant",
                    content=assistant_text or "",
                )
            )
            await session.commit()
    except Exception as exc:
        logger.exception("Failed to persist ai chat log user_tg_id=%s: %s", user_tg_id, exc)


async def _process_message(bot: Bot, storage: RedisStorage, message: AbstractIncomingMessage, bot_id: int) -> None:
    started_ts = datetime.utcnow().timestamp()
    started_monotonic = asyncio.get_running_loop().time()
    try:
        payload = json.loads(message.body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON payload: %r", message.body)
        await message.nack(requeue=False)
        return

    chat_id = payload.get("chat_id")
    user_id = payload.get("user_id") or chat_id
    request_id = str(payload.get("request_id") or "-")
    enqueued_at_ts = payload.get("enqueued_at_ts")
    retry_count = _get_retry_count(message)
    can_broadcast_ai_posts = bool(payload.get("can_broadcast_ai_posts") or payload.get("is_admin"))
    messages_payload = payload.get("messages")

    if not chat_id or not messages_payload:
        logger.error("Missing chat_id or messages in payload: %s", payload)
        await message.nack(requeue=False)
        return

    try:
        user_text = ""
        if isinstance(messages_payload, list):
            for item in reversed(messages_payload):
                if isinstance(item, dict) and item.get("role") == "user":
                    user_text = str(item.get("content") or "")
                    break

        enriched_user_text = _enrich_query_with_period(user_text, messages_payload)

        provider, _, _, _ = await _resolve_ai_config()
        db_stats = await _collect_db_stats(enriched_user_text)
        logger.info("rid=%s chat_id=%s provider=%s context=%s", request_id, chat_id, provider, db_stats)

        if _is_order_id_query(user_text):
            ai_answer = await _build_order_ids_answer(user_text)
        elif _is_today_summary_query(enriched_user_text):
            start_dt, end_dt, _ = _resolve_report_period(enriched_user_text)
            sales_details = await _collect_sales_details_for_period(start_dt, end_dt)
            ai_answer = _build_factual_full_report(db_stats, sales_details)
        elif _is_financial_query(user_text):
            if _wants_sales_details(user_text):
                start_dt, end_dt, _ = _resolve_report_period(enriched_user_text)
                sales_details = await _collect_sales_details_for_period(start_dt, end_dt)
                ai_answer = _build_factual_full_report(db_stats, sales_details)
            else:
                ai_answer = _build_factual_finance_answer(db_stats)
        else:
            db_stats_block = _build_db_stats_block(db_stats)
            enriched_messages_payload = _inject_db_stats_into_system(messages_payload, db_stats_block)
            ai_answer = await _request_ai(enriched_messages_payload)
        product_ids = _extract_show_ids(ai_answer)
        clean_answer = _strip_show_tags(ai_answer)
        if not clean_answer:
            clean_answer = "AI is busy. Try another question."

        await _persist_ai_chat_log(int(user_id), user_text, clean_answer)

        allow_broadcast = can_broadcast_ai_posts and (
            _is_post_request(user_text)
            or _is_broadcast_content(user_text)
            or _is_broadcast_content(clean_answer)
        )
        reply_markup = admin_kb() if allow_broadcast else None
        await _send_safe_html(bot, int(chat_id), clean_answer, reply_markup=reply_markup)
        await _send_product_cards(bot, int(chat_id), product_ids)
        await _append_history(storage, bot_id, int(chat_id), int(user_id), ai_answer)
        if allow_broadcast:
            await _set_pending_post(storage, bot_id, int(chat_id), int(user_id), clean_answer)
        await message.ack()
        processed_ms = int((asyncio.get_running_loop().time() - started_monotonic) * 1000)
        queue_lag_ms = None
        try:
            if enqueued_at_ts is not None:
                queue_lag_ms = int((started_ts - float(enqueued_at_ts)) * 1000)
        except (TypeError, ValueError):
            queue_lag_ms = None
        logger.info(
            "rid=%s chat_id=%s done retry=%s processed_ms=%s queue_lag_ms=%s",
            request_id,
            chat_id,
            retry_count,
            processed_ms,
            queue_lag_ms,
        )
    except Exception as exc:
        error_text = str(exc)
        logger.exception("AI generation failed rid=%s chat_id=%s retry=%s: %s", request_id, chat_id, retry_count, exc)
        try:
            if retry_count < max(0, settings.ai_max_retries):
                await _republish_with_retry(message, payload, retry_count, error_text)
                await message.ack()
                logger.warning(
                    "rid=%s chat_id=%s requeued retry=%s/%s",
                    request_id,
                    chat_id,
                    retry_count + 1,
                    settings.ai_max_retries,
                )
            else:
                await _publish_to_dlq(message, payload, retry_count, error_text)
                await message.ack()
                logger.error("rid=%s chat_id=%s moved_to_dlq retries=%s", request_id, chat_id, retry_count)
                try:
                    await bot.send_message(int(chat_id), "⚠️ Не удалось обработать запрос. Попробуйте переформулировать или повторить позже.")
                except Exception as notify_exc:
                    logger.warning("Failed to notify chat about dropped message chat_id=%s: %s", chat_id, notify_exc)
        except Exception as handling_exc:
            logger.exception("rid=%s chat_id=%s failure-handling-error: %s", request_id, chat_id, handling_exc)
            await message.nack(requeue=True)


async def _consume_queue(bot: Bot, storage: RedisStorage, bot_id: int) -> None:
    retry_delay = 2
    while True:
        try:
            connection = await aio_pika.connect_robust(settings.rabbitmq_url)
            async with connection:
                channel = await connection.channel()
                await channel.set_qos(prefetch_count=4)
                queue = await channel.declare_queue(QUEUE_NAME, durable=True)
                await channel.declare_queue(DLQ_QUEUE_NAME, durable=True)

                async with queue.iterator() as queue_iter:
                    async for incoming in queue_iter:
                        await _process_message(bot, storage, incoming, bot_id)
        except Exception as exc:
            logger.exception("Queue consumer crashed, retry in %ss: %s", retry_delay, exc)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)


async def main() -> None:
    try:
        await _resolve_ai_config()
    except RuntimeError as exc:
        logger.error("AI provider configuration error: %s", exc)
        sys.exit(1)

    async with async_session_maker() as session:
        tenant = await resolve_tenant_by_bot_token(session, settings.bot_token)
    runtime_bot_token = tenant.bot_token or settings.bot_token
    bot_id = int(runtime_bot_token.split(":", 1)[0])
    bot = Bot(token=runtime_bot_token)
    storage = RedisStorage.from_url(settings.redis_url)
    try:
        await _consume_queue(bot, storage, bot_id)
    finally:
        await bot.session.close()
        await storage.close()


if __name__ == "__main__":
    log_level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )
    asyncio.run(main())
