from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = os.getenv("ENV_FILE", ".env")
ENV_PATH = BASE_DIR / ENV_FILE

# load_dotenv не нужен, если переменные уже в env от --env-file


@dataclass
class Settings:
    bot_token: str
    owner_id: int
    admin_ids: set[int]
    db_url: str
    redis_url: str
    rabbitmq_url: str
    db_pool_size: int
    db_max_overflow: int
    db_pool_timeout: int

    # API ключи для AI (опционально)
    groq_api_key: str
    deepseek_api_key: str
    ollama_api_key: str
    ai_provider: str
    ai_model: str
    groq_model: str
    deepseek_model: str

    # Настройки лимитов
    ai_client_start_quota: int
    ai_client_bonus_quota: int
    max_photos_per_model: int
    ai_request_timeout_sec: int
    ai_min_interval_sec: int
    ai_rate_limit_window_sec: int
    ai_rate_limit_max_requests: int
    log_level: str
    max_queue_payload_bytes: int
    ai_max_retries: int
    ai_dlq_queue_name: str

    timezone: str

    # Тексты кнопок
    button_catalog: str
    button_cart: str
    button_orders: str
    button_ai: str
    button_support: str

    @classmethod
    def from_env(cls) -> "Settings":
        # Проверка критических переменных
        token = os.getenv("BOT_TOKEN")
        if not token:
            logger.critical("BOT_TOKEN is not set in environment")
            sys.exit(1)

        owner = os.getenv("OWNER_ID")
        if not owner:
            logger.critical("OWNER_ID is not set in environment")
            sys.exit(1)

        admin_ids_raw = os.getenv("ADMIN_IDS", "")
        admin_ids: set[int] = set()
        for part in admin_ids_raw.split(","):
            value = part.strip()
            if value.isdigit():
                admin_ids.add(int(value))

        admin_ids.add(int(owner))

        return cls(
            bot_token=token,
            owner_id=int(owner),
            admin_ids=admin_ids,
            db_url=os.getenv("DB_URL", "sqlite+aiosqlite:///tg_shop.db"),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            rabbitmq_url=os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"),
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            ollama_api_key=os.getenv("OLLAMA_API_KEY", ""),
            ai_provider=os.getenv("AI_PROVIDER", "groq").strip().lower(),
            ai_model=os.getenv("AI_MODEL", "").strip(),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
            ai_client_start_quota=int(os.getenv("AI_CLIENT_START_QUOTA", 25)),
            ai_client_bonus_quota=int(os.getenv("AI_CLIENT_BONUS_QUOTA", 5)),
            max_photos_per_model=int(os.getenv("MAX_PHOTOS_PER_MODEL", 10)),
            ai_request_timeout_sec=int(os.getenv("AI_REQUEST_TIMEOUT_SEC", 60)),
            ai_min_interval_sec=int(os.getenv("AI_MIN_INTERVAL_SEC", 2)),
            ai_rate_limit_window_sec=int(os.getenv("AI_RATE_LIMIT_WINDOW_SEC", 60)),
            ai_rate_limit_max_requests=int(os.getenv("AI_RATE_LIMIT_MAX_REQUESTS", 20)),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            max_queue_payload_bytes=int(os.getenv("MAX_QUEUE_PAYLOAD_BYTES", 65536)),
            ai_max_retries=int(os.getenv("AI_MAX_RETRIES", 2)),
            ai_dlq_queue_name=os.getenv("AI_DLQ_QUEUE_NAME", "ai_generation_dlq"),
            timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
            db_pool_size=int(os.getenv("DB_POOL_SIZE", 20)),
            db_max_overflow=int(os.getenv("DB_MAX_OVERFLOW", 20)),
            db_pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", 30)),
            button_catalog=os.getenv("BUTTON_CATALOG", "🛍 Каталог"),
            button_cart=os.getenv("BUTTON_CART", "🛒 Корзина"),
            button_orders=os.getenv("BUTTON_ORDERS", "📦 Заказы"),
            button_ai=os.getenv("BUTTON_AI", "✨ AI-Консультант"),
            button_support=os.getenv("BUTTON_SUPPORT", "💬 Поддержка"),
        )


settings = Settings.from_env()