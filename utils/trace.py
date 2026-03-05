"""Structured logging helpers: trace_id via contextvars.

Каждый входящий запрос (HTTP или Telegram update) получает уникальный trace_id.
Все log-записи в рамках этого запроса автоматически содержат этот trace_id.

Использование:
    from utils.trace import get_trace_id, set_trace_id, new_trace_id

    # В middleware:
    tid = new_trace_id()          # генерируем + сохраняем в contextvar
    logger.info("start", extra={"trace_id": get_trace_id()})

    # В любом хендлере/сервисе:
    from utils.trace import get_trace_id
    logger.info("processing order %s | trace=%s", order_id, get_trace_id())
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar

# ContextVar живёт в рамках одного asyncio.Task → одного запроса/апдейта
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


def new_trace_id() -> str:
    """Генерирует новый trace_id, сохраняет в contextvar и возвращает его."""
    tid = uuid.uuid4().hex[:16]   # 16 hex-символов, достаточно читаемо в логах
    _trace_id_var.set(tid)
    return tid


def set_trace_id(tid: str) -> None:
    """Устанавливает внешний trace_id (например из заголовка X-Request-ID)."""
    _trace_id_var.set(tid[:32])   # ограничиваем длину для безопасности


def get_trace_id() -> str:
    """Возвращает текущий trace_id или '-' если не установлен."""
    return _trace_id_var.get()
