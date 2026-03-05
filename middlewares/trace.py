"""TraceMiddleware: устанавливает trace_id для каждого Telegram-апдейта.

Регистрируется до DbSessionMiddleware:
    dp.update.outer_middleware(TraceMiddleware())

После этого во всех хендлерах доступно:
    from utils.trace import get_trace_id
    logger.info("handler called | trace=%s", get_trace_id())

Trace_id передаётся через contextvars → автоматически изолирован
между параллельными апдейтами (каждый asyncio.Task имеет свой контекст).
"""
from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from loguru import logger

from utils.trace import new_trace_id, get_trace_id


class TraceMiddleware(BaseMiddleware):
    """Генерирует trace_id на каждый incoming Telegram update."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tid = new_trace_id()
        # Пробрасываем trace_id в data — хендлер может забрать его явно
        data["trace_id"] = tid

        # Определяем тип события для лога
        event_type = type(event).__name__
        user_id = _extract_user_id(event)

        logger.bind(trace_id=tid).debug(
            "tg_update type={} user_id={}", event_type, user_id
        )

        try:
            result = await handler(event, data)
        except Exception as exc:
            logger.bind(trace_id=get_trace_id()).error(
                "tg_update_error type={} user_id={} error={!r}",
                event_type,
                user_id,
                exc,
            )
            raise
        else:
            logger.bind(trace_id=get_trace_id()).debug(
                "tg_update_done type={} user_id={}", event_type, user_id
            )
            return result


def _extract_user_id(event: TelegramObject) -> int | None:
    """Безопасно достаём user_id из любого типа апдейта."""
    from_user = getattr(event, "from_user", None)
    if from_user:
        return from_user.id
    # Message, CallbackQuery, etc.
    message = getattr(event, "message", None)
    if message:
        from_user = getattr(message, "from_user", None)
        if from_user:
            return from_user.id
    return None
