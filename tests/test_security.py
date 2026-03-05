"""Security-related tests: html escaping, CORS config, admin key validation."""
from __future__ import annotations

import os
import sys
import unittest
from html import escape

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OWNER_ID", "1")


class HtmlEscapeTests(unittest.TestCase):
    """Проверяем что пользовательские данные escaping'ятся перед вставкой в HTML."""

    def test_html_tags_in_full_name_are_escaped(self):
        """Имя вида '<Web> & User' должно стать '&lt;Web&gt; &amp; User'."""
        raw = "<Web> & User"
        safe = escape(raw)
        self.assertNotIn("<Web>", safe)
        self.assertIn("&lt;Web&gt;", safe)
        self.assertIn("&amp;", safe)

    def test_script_injection_in_phone_is_escaped(self):
        """Телефон с <script> тегом должен быть экранирован."""
        raw = "+7<script>alert(1)</script>"
        safe = escape(raw)
        self.assertNotIn("<script>", safe)
        self.assertIn("&lt;script&gt;", safe)

    def test_safe_name_unchanged(self):
        """Обычное имя остаётся нетронутым."""
        raw = "Иван Петров"
        self.assertEqual(escape(raw), raw)

    def test_empty_string_safe(self):
        """Пустая строка не ломает escape."""
        self.assertEqual(escape(""), "")

    def test_none_handled_via_or(self):
        """None через 'or' превращается в пустую строку."""
        value = None
        safe = escape(value or "")
        self.assertEqual(safe, "")


class WebApiCorsConfigTests(unittest.TestCase):
    """Проверяем что CORS origins читаются из env переменной."""

    @staticmethod
    def _parse_origins(raw: str) -> list[str]:
        if not raw.strip():
            raise ValueError("CORS_ORIGINS must be set")
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        if not origins:
            raise ValueError("CORS_ORIGINS must contain at least one origin")
        if any(origin == "*" for origin in origins):
            raise ValueError("Wildcard is forbidden")
        return origins

    def test_cors_origins_from_env(self):
        os.environ["CORS_ORIGINS"] = "https://example.com,https://shop.example.com"
        raw = os.getenv("CORS_ORIGINS", "")
        origins = self._parse_origins(raw)
        self.assertEqual(origins, ["https://example.com", "https://shop.example.com"])

    def test_cors_empty_env_is_rejected(self):
        os.environ["CORS_ORIGINS"] = ""
        raw = os.getenv("CORS_ORIGINS", "")
        with self.assertRaises(ValueError):
            self._parse_origins(raw)

    def test_cors_wildcard_is_rejected(self):
        with self.assertRaises(ValueError):
            self._parse_origins("*")

    def tearDown(self):
        os.environ.pop("CORS_ORIGINS", None)


class AdminKeyValidationTests(unittest.TestCase):
    """Проверяем логику Bearer авторизации для admin API."""

    @staticmethod
    def _extract_bearer_token(authorization: str | None) -> str | None:
        if not authorization:
            return None
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None
        return token.strip()

    def _validate(self, authorization: str | None, expected_key: str = "secret123") -> bool:
        """Имитирует проверку токена из Authorization: Bearer <token>."""
        token = self._extract_bearer_token(authorization)
        if not token or token != expected_key:
            return False
        return True

    def test_correct_key_passes(self):
        self.assertTrue(self._validate("Bearer secret123"))

    def test_wrong_key_fails(self):
        self.assertFalse(self._validate("Bearer wrong"))

    def test_empty_key_fails(self):
        self.assertFalse(self._validate(""))

    def test_none_key_fails(self):
        self.assertFalse(self._validate(None))

    def test_non_bearer_scheme_fails(self):
        self.assertFalse(self._validate("Token secret123"))

    def test_key_with_spaces_stripped(self):
        self.assertTrue(self._validate("Bearer   secret123  "))


class OrdersStatsEscapeTests(unittest.TestCase):
    """Проверяем что orders_stats.py использует escape для HTML-сообщений."""

    def test_escape_applied_in_card_text(self):
        from handlers.owner_main_parts import orders_stats
        import inspect
        source = inspect.getsource(orders_stats)
        # Убеждаемся что escape импортирован и используется в card_text
        self.assertIn("from html import escape", source)
        self.assertIn("escape(order.full_name", source)

    def test_escape_applied_to_phone(self):
        from handlers.owner_main_parts import orders_stats
        import inspect
        source = inspect.getsource(orders_stats)
        self.assertIn("escape(order.phone", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
