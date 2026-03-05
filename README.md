# MLI Shop — Telegram-магазин + Web Storefront

![CI](https://github.com/thissthanss45-tech/mli_shop_project/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11-blue)
![aiogram](https://img.shields.io/badge/aiogram-3.x-009ddc)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-00c7b7)

Полноценный Telegram-магазин с web-витриной, AI-консультантом, ERP Excel-отчётами и Prometheus-мониторингом.

**Стек:** Python 3.11 · aiogram 3.x · FastAPI · asyncpg · PostgreSQL · Redis · RabbitMQ (aio_pika) · Qdrant · Docker Compose · Alembic · pytest (93 теста)

## Что в проекте готово

- Telegram bot (`shop.py`) + worker (`worker.py`) на общей БД.
- Web storefront и FastAPI (`web_api.py`) с:
	- каталогом и карточкой товара,
	- корзиной и web-checkout в БД,
	- AI-чатом,
	- админ-панелью `/admin` (CRUD товаров + Excel отчёт за период).
- Excel ERP отчёт: листы `Продажи`, `Склад`, `Движение`.

## Production запуск (Docker Compose)

1. Проверьте `.env`:

- `BOT_TOKEN`, `OWNER_ID`, `DB_URL`, `REDIS_URL`, `RABBITMQ_URL`
- `WEB_ADMIN_KEY` (обязателен, используется для Bearer-доступа к admin API)
- `CORS_ORIGINS` (обязательный whitelist origins, например `https://shop.example.com,https://admin.shop.example.com`)
- опционально `WEB_API_PORT` (по умолчанию `8000`)
- `TLS_DOMAIN` для HTTPS reverse proxy (например, `shop.example.com`)

2. Запустите прод-стек:

```bash
docker compose up -d --build db redis rabbitmq bot worker web_api
```

Для локальной разработки с bind mount исходников используйте dev-override:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build db redis rabbitmq bot worker web_api
```

3. Проверка статуса:

```bash
docker compose ps
docker compose logs --no-color --tail=120 web_api
curl -sS http://127.0.0.1:${WEB_API_PORT:-8000}/api/health
```

## Основные web URL

- Витрина: `http://<host>:<WEB_API_PORT>/`
- Админка: `http://<host>:<WEB_API_PORT>/admin`
- Swagger: `http://<host>:<WEB_API_PORT>/docs`

### Admin API авторизация

- Все `/api/admin/*` endpoint'ы принимают только заголовок `Authorization: Bearer <WEB_ADMIN_KEY>`.
- Query-параметр `admin_key` больше не используется.

Если порт `8000` уже занят на сервере/хосте, задайте другой:

```bash
export WEB_API_PORT=8001
python3 web_api.py
```

### Локальный запуск web_api (без правки `.env`)

Если в `.env` `DB_URL` содержит хост `db` (docker hostname), для запуска на хосте используйте:

```bash
./scripts/run_web_api_local.sh
```

Скрипт автоматически:

- подгружает `.env`,
- выбирает порт `WEB_API_PORT` (по умолчанию `8001`),
- подменяет `db` на IP контейнера PostgreSQL (`mli_shop_project-db-1`) для локального запуска.

### Локальный запуск Telegram-бота (без правки `.env`)

Если бот запускается на хосте, а в `DB_URL` указан docker-хост `db`, используйте:

```bash
./scripts/run_bot_local.sh
```

Скрипт подгружает `.env` и автоматически подменяет `db` на IP контейнера PostgreSQL для локального запуска `shop.py`.

Важно: одновременно должен работать только один инстанс бота (либо локальный `shop.py`, либо `docker compose` сервис `bot`).
Иначе Telegram вернёт `TelegramConflictError`.

## HTTPS (Nginx + Let's Encrypt)

В проект добавлен reverse proxy `nginx` и сервис `certbot`.

### Первый выпуск сертификата

```bash
chmod +x scripts/setup_tls.sh scripts/renew_tls.sh
./scripts/setup_tls.sh <domain> <email>
```

Пример:

```bash
./scripts/setup_tls.sh shop.example.com admin@shop.example.com
```

После успешного выпуска:

- `https://<domain>/` — витрина
- `https://<domain>/admin` — админка
- `https://<domain>/docs` — API docs

### Продление сертификата

```bash
./scripts/renew_tls.sh <domain>
```

Рекомендуется добавить в cron (раз в день):

```bash
0 3 * * * cd /path/to/mli_shop_project && ./scripts/renew_tls.sh <domain> >/var/log/mli_tls_renew.log 2>&1
```

## Быстрый smoke-test после релиза

- `/api/health` возвращает `status=ok`.
- `/admin`: загрузка таблицы товаров, `Сохранить`, `Удалить`.
- `/admin`: выгрузка отчёта за период (`period.xlsx`).
- Создание web-заказа отражается в БД и уходит уведомление в Telegram owner/staff.

## CI / Quality Gate

- В репозитории настроен GitHub Actions workflow: `.github/workflows/ci.yml`.
- На каждом push/PR выполняются:
	- `pytest`
	- `ruff check .`
	- `mypy config.py web_api.py database/orders_repo.py utils/mq.py`

## Мониторинг / Observability

- API отдаёт Prometheus-совместимые метрики по `GET /api/metrics`.
- Метрики включают:
	- `app_http_requests_total` — счётчик HTTP запросов (method/path/status)
	- `app_http_request_duration_seconds` — histogram latency
	- `app_uptime_seconds` — uptime процесса
- Каждый HTTP ответ содержит `X-Request-ID`; если клиент не передал header, ID генерируется на сервере.

Проверка вручную:

```bash
curl -sS http://127.0.0.1:${WEB_API_PORT:-8000}/api/metrics | head -n 40
```

### Prometheus + Grafana (готовый стек)

Добавлен отдельный compose-override: `docker-compose.monitoring.yml`.

Запуск:

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d --build
```

Если используете dev bind-mount, добавьте и dev override:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.monitoring.yml up -d --build
```

Где смотреть:

- Prometheus UI: `http://<host>:${PROMETHEUS_PORT:-9090}`
- Grafana UI: `http://<host>:${GRAFANA_PORT:-3000}`
	- логин/пароль по умолчанию: `admin` / `admin`
	- dashboard уже подхватывается автоматически: **MLI Shop API Overview**

Быстрая проверка scrape:

```bash
curl -sS http://127.0.0.1:${PROMETHEUS_PORT:-9090}/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health, scrapeUrl: .scrapeUrl}'
```

## AI провайдеры (Groq / DeepSeek)

### Настройка через .env

```
AI_PROVIDER=groq
AI_MODEL=
GROQ_API_KEY=...
DEEPSEEK_API_KEY=...
GROQ_MODEL=llama-3.3-70b-versatile
DEEPSEEK_MODEL=deepseek-chat
```

`AI_PROVIDER` поддерживает значения: `groq`, `deepseek`.
Если `AI_MODEL` пустой, берется модель из `GROQ_MODEL`/`DEEPSEEK_MODEL`.

### Переключение через админ-команду

- Проверить текущие настройки: `/ai_provider`
- Переключить провайдера: `/ai_provider groq` или `/ai_provider deepseek`
- Указать модель явно: `/ai_provider deepseek deepseek-chat`
- Сбросить на значения из `.env`: `/ai_provider reset`