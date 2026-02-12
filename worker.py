from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import sys

import aiohttp
import aio_pika
from aio_pika.abc import AbstractIncomingMessage
from aiogram import Bot
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import InlineKeyboardMarkup

from config import settings
from database.catalog_repo import CatalogRepo
from database.db_manager import async_session_maker
from utils.admin_kb import admin_kb
from utils.cards import send_product_card

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = "llama-3.3-70b-versatile"
QUEUE_NAME = "ai_generation"
MAX_HISTORY_ITEMS = 12

logger = logging.getLogger(__name__)


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
        if len(current_part) + len(line) + 1 > max_length:
            parts.append(current_part)
            current_part = line + "\n"
        else:
            current_part += line + "\n"

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
        "отправить",
        "клиентам",
        "поздравить",
        "праздник",
        "акция",
        "скидка",
    ]
    return any(keyword in lowered for keyword in keywords)


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


async def _request_groq(messages_payload: list[dict]) -> str:
    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL_NAME,
        "messages": messages_payload,
        "temperature": 0.5,
        "max_tokens": 800,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(GROQ_URL, json=payload, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Groq API error {resp.status}: {body}")
            result = await resp.json()

    return result["choices"][0]["message"]["content"]


async def _append_history(storage: RedisStorage, bot_id: int, chat_id: int, user_id: int, ai_answer: str) -> None:
    key = StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=user_id)
    data = await storage.get_data(key)
    history = data.get("history", [])
    if len(history) > MAX_HISTORY_ITEMS:
        history = history[-MAX_HISTORY_ITEMS:]
    history.append({"role": "assistant", "content": ai_answer})
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


async def _process_message(bot: Bot, storage: RedisStorage, message: AbstractIncomingMessage, bot_id: int) -> None:
    try:
        payload = json.loads(message.body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON payload: %r", message.body)
        await message.nack(requeue=False)
        return

    chat_id = payload.get("chat_id")
    user_id = payload.get("user_id") or chat_id
    is_admin = bool(payload.get("is_admin"))
    messages_payload = payload.get("messages")

    if not chat_id or not messages_payload:
        logger.error("Missing chat_id or messages in payload: %s", payload)
        await message.nack(requeue=False)
        return

    try:
        ai_answer = await _request_groq(messages_payload)
        product_ids = _extract_show_ids(ai_answer)
        clean_answer = _strip_show_tags(ai_answer)
        if not clean_answer:
            clean_answer = "AI is busy. Try another question."

        user_text = ""
        if isinstance(messages_payload, list):
            for item in reversed(messages_payload):
                if isinstance(item, dict) and item.get("role") == "user":
                    user_text = str(item.get("content") or "")
                    break

        allow_broadcast = is_admin and (
            _is_broadcast_content(ai_answer) or _is_broadcast_content(user_text)
        )
        reply_markup = admin_kb() if allow_broadcast else None
        await _send_safe_html(bot, int(chat_id), clean_answer, reply_markup=reply_markup)
        await _send_product_cards(bot, int(chat_id), product_ids)
        await _append_history(storage, bot_id, int(chat_id), int(user_id), ai_answer)
        if allow_broadcast:
            await _set_pending_post(storage, bot_id, int(chat_id), int(user_id), clean_answer)
        await message.ack()
    except Exception as exc:
        logger.exception("AI generation failed for chat_id=%s: %s", chat_id, exc)
        await message.nack(requeue=True)


async def _consume_queue(bot: Bot, storage: RedisStorage, bot_id: int) -> None:
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=4)
        queue = await channel.declare_queue(QUEUE_NAME, durable=True)

        async with queue.iterator() as queue_iter:
            async for incoming in queue_iter:
                await _process_message(bot, storage, incoming, bot_id)


async def main() -> None:
    if not settings.groq_api_key:
        logger.error("GROQ_API_KEY is missing. Worker cannot start.")
        sys.exit(1)

    bot_id = int(settings.bot_token.split(":", 1)[0])
    bot = Bot(token=settings.bot_token)
    storage = RedisStorage.from_url(settings.redis_url)
    try:
        await _consume_queue(bot, storage, bot_id)
    finally:
        await bot.session.close()
        await storage.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
