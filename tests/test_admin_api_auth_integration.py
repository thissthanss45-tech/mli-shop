from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient


os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")
os.environ.setdefault("WEB_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("CORS_ORIGINS", "https://example.com")

from web_api import app  # noqa: E402


class AdminApiAuthIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_admin_meta_requires_authorization_header(self):
        response = self.client.get("/api/admin/meta")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Authorization", response.json().get("detail", ""))

    def test_admin_meta_rejects_non_bearer_scheme(self):
        response = self.client.get(
            "/api/admin/meta",
            headers={"Authorization": "Token test-admin-key"},
        )
        self.assertEqual(response.status_code, 401)

    def test_admin_meta_rejects_invalid_bearer_token(self):
        response = self.client.get(
            "/api/admin/meta",
            headers={"Authorization": "Bearer wrong-token"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
