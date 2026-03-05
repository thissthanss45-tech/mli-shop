from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient


os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")
os.environ.setdefault("WEB_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("CORS_ORIGINS", "https://example.com")

from web_api import app  # noqa: E402


class RequestContextMiddlewareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_ping_response_contains_request_id_header(self):
        response = self.client.get("/api/ping")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("X-Request-ID"))

    def test_preserves_incoming_request_id(self):
        rid = "test-rid-123"
        response = self.client.get("/api/ping", headers={"X-Request-ID": rid})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Request-ID"), rid)

    def test_metrics_endpoint_is_prometheus_compatible(self):
        self.client.get("/api/ping")
        response = self.client.get("/api/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers.get("content-type", ""))
        body = response.text
        self.assertIn("# TYPE app_http_requests_total counter", body)
        self.assertIn("# TYPE app_http_request_duration_seconds histogram", body)
        self.assertIn('app_http_requests_total{method="GET",path="/api/ping",status="200"}', body)
        self.assertIn('app_http_request_duration_seconds_count{method="GET",path="/api/ping"}', body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
