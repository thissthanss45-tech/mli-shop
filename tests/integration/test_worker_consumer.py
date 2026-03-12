from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import worker
from database.db_manager import Base
from models import AIChatLog, Tenant
from utils.tenants import ensure_default_tenant


class FakeStorage:
    def __init__(self) -> None:
        self.data: dict[tuple[int, int, int], dict] = {}

    async def get_data(self, key):
        return dict(self.data.get((key.bot_id, key.chat_id, key.user_id), {}))

    async def set_data(self, key, value):
        self.data[(key.bot_id, key.chat_id, key.user_id)] = dict(value)


class FakeBot:
    def __init__(self, token: str) -> None:
        self.token = token
        self.sent_messages: list[dict] = []

    async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None, reply_markup=None):
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
        )


class FakeIncomingMessage:
    def __init__(self, payload: dict) -> None:
        self.body = json.dumps(payload).encode("utf-8")
        self.headers = {}
        self.ack = AsyncMock()
        self.nack = AsyncMock()


class FakeQueueIterator:
    def __init__(self, message: FakeIncomingMessage) -> None:
        self.message = message
        self.yielded = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.yielded:
            self.yielded = True
            return self.message
        raise asyncio.CancelledError()


class FakeQueue:
    def __init__(self, message: FakeIncomingMessage) -> None:
        self.message = message

    def iterator(self):
        return FakeQueueIterator(self.message)


class FakeChannel:
    def __init__(self, message: FakeIncomingMessage) -> None:
        self.message = message

    async def set_qos(self, prefetch_count: int):
        return None

    async def declare_queue(self, name: str, durable: bool = True):
        return FakeQueue(self.message)


class FakeConnection:
    def __init__(self, message: FakeIncomingMessage) -> None:
        self.message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def channel(self):
        return FakeChannel(self.message)


def _make_engine(db_path: str):
    return create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )


async def _init_db(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def test_worker_consumer_processes_mocked_queue_with_tenant_bot_token(tmp_path, monkeypatch):
    async def scenario() -> None:
        engine = _make_engine(str(tmp_path / "worker_consumer.db"))
        await _init_db(engine)
        maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        original_maker = worker.async_session_maker
        worker.async_session_maker = maker
        original_bot_token = worker.settings.bot_token
        tenant_bot_token = "777777:tenant-specific-token"
        monkeypatch.setattr(worker.settings, "bot_token", tenant_bot_token)

        try:
            async with maker() as session:
                tenant = await ensure_default_tenant(session)
                tenant.bot_token = tenant_bot_token
                tenant.title = "Worker Tenant"
                await session.commit()

            fake_storage = FakeStorage()
            fake_bot = FakeBot(token=tenant_bot_token)
            message = FakeIncomingMessage(
                {
                    "chat_id": 12345,
                    "user_id": 12345,
                    "request_id": "worker-itest",
                    "messages": [
                        {"role": "system", "content": "system"},
                        {"role": "user", "content": "что у нас за сегодня"},
                    ],
                }
            )

            with patch.object(worker.aio_pika, "connect_robust", AsyncMock(return_value=FakeConnection(message))), \
                 patch.object(worker, "_resolve_ai_config", AsyncMock(return_value=("groq", "key", "url", "model"))), \
                 patch.object(worker, "send_product_card", AsyncMock()):
                try:
                    await worker._consume_queue(fake_bot, fake_storage, bot_id=777777)
                except asyncio.CancelledError:
                    pass

            assert fake_bot.token == tenant_bot_token
            assert message.ack.await_count == 1
            assert message.nack.await_count == 0
            assert fake_bot.sent_messages
            assert fake_bot.sent_messages[0]["chat_id"] == 12345
            assert "ФИНАНСОВЫЙ" in fake_bot.sent_messages[0]["text"] or "ПОЛНЫЙ ОТЧЕТ" in fake_bot.sent_messages[0]["text"]

            async with maker() as session:
                tenant_row = await session.scalar(select(Tenant).where(Tenant.bot_token == tenant_bot_token))
                logs = (await session.execute(select(AIChatLog).order_by(AIChatLog.id.asc()))).scalars().all()

            assert tenant_row is not None
            assert len(logs) == 2
            assert all(log.tenant_id == tenant_row.id for log in logs)
            assert logs[0].role == "user"
            assert logs[1].role == "assistant"
        finally:
            worker.async_session_maker = original_maker
            monkeypatch.setattr(worker.settings, "bot_token", original_bot_token)
            await engine.dispose()

    asyncio.run(scenario())