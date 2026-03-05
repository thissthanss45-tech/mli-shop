from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")
os.environ.setdefault("WEB_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("CORS_ORIGINS", "https://example.com")

from web_api import RateLimitMiddleware  # noqa: E402
from utils import mq  # noqa: E402


class RateLimitRedisFailureTests(unittest.TestCase):
    def test_rate_limiter_does_not_break_when_redis_unavailable(self):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, max_requests=2, window_sec=60)

        @app.get("/probe")
        async def probe():
            return {"status": "ok"}

        async def _boom(self):
            raise RuntimeError("redis unavailable")

        with patch.object(RateLimitMiddleware, "_get_redis", _boom):
            client = TestClient(app)
            response = client.get("/probe")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json().get("status"), "ok")


class RabbitFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_task_to_queue_propagates_rabbit_connection_error(self):
        with patch("utils.mq.get_rabbitmq_connection", new=AsyncMock(side_effect=RuntimeError("rabbit down"))):
            with self.assertRaises(RuntimeError):
                await mq.send_task_to_queue("ai_generation", {"chat_id": 1, "messages": [{"role": "user", "content": "hi"}]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
