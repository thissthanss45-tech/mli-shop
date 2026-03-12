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

## Tenant SaaS operations

- Операционный runbook по онбордингу магазинов, деплою и мониторингу: [TENANT_OPERATIONS_RUNBOOK.md](TENANT_OPERATIONS_RUNBOOK.md)
- Tenant-specific smoke endpoint: `GET /api/health/tenant?tenant=<slug>`
- Tenant-specific Prometheus endpoint: `GET /api/metrics/tenants`
- Admin API для пресетов ниш и массового provisioning:
	- `GET /api/admin/tenant-presets`
	- `POST /api/admin/tenants`
	- `POST /api/admin/tenants/bulk-provision`
- Preset provisioning теперь создаёт не только категории и бренды, но и стартовые demo-товары.

## Production запуск (Docker Compose)

### Быстрый запуск одного Telegram-магазина

Если нужен один активный Telegram-магазин на текущем сервере, используйте launcher:

```bash
cd /root/mli_shop_project
chmod +x scripts/launch_tg_shop.sh scripts/launch_flower_shop.sh
./scripts/launch_flower_shop.sh --bot-token <TOKEN_FROM_BOTFATHER> --owner-id <YOUR_TG_ID>
```

Что делает launcher:

- создаёт env-файл для запуска;
- поднимает `db`, `redis`, `rabbitmq`;
- создаёт tenant магазина с preset `flowers` и demo-товарами;
- стартует `web_api`, `worker`, `bot`;
- печатает smoke-check команды.

Важно: текущий `shop.py` поднимает polling только на одном `BOT_TOKEN`, поэтому этот сценарий рассчитан на один активный Telegram-магазин на один bot process.

1. Проверьте `.env`:

- `BOT_TOKEN`, `OWNER_ID`, `DB_URL`, `REDIS_URL`, `RABBITMQ_URL`
- `WEB_ADMIN_KEY` (обязателен, используется для Bearer-доступа к admin API)
- `CORS_ORIGINS` (обязательный whitelist origins, например `https://shop.example.com,https://admin.shop.example.com`)
- опционально `WEB_API_PORT` (по умолчанию `8000`)
- `TLS_DOMAIN` для HTTPS reverse proxy (например, `shop.example.com`)

Важно для production:

- используйте `.env.example` как шаблон и храните реальные `.env*` только на сервере;
- если какой-либо env-файл с реальными ключами уже попал в git-историю, немедленно ротируйте `BOT_TOKEN`, `WEB_ADMIN_KEY`, `GROQ_API_KEY`, `DEEPSEEK_API_KEY`, пароли PostgreSQL и RabbitMQ;
- перед запуском заполните `TLS_DOMAIN`, иначе `docker compose` будет поднимать стек с предупреждением и без корректного TLS-конфига.

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
- `/api/health/tenant?tenant=<slug>` возвращает tenant-specific smoke status и счетчики справочников/ролей.
- `/admin`: загрузка таблицы товаров, `Сохранить`, `Удалить`.
- `/admin`: выгрузка отчёта за период (`period.xlsx`).
- Создание web-заказа отражается в БД и уходит уведомление в Telegram owner/staff.

Для полного operational прогона и onboarding новых магазинов используйте [TENANT_OPERATIONS_RUNBOOK.md](TENANT_OPERATIONS_RUNBOOK.md).

## CI / Quality Gate

- В репозитории настроен GitHub Actions workflow: `.github/workflows/ci.yml`.
- На каждом push/PR выполняются:
	- `pytest`
	- `ruff check .`
	- `mypy config.py web_api.py database/orders_repo.py utils/mq.py`

## Мониторинг / Observability

- API отдаёт Prometheus-совместимые метрики по `GET /api/metrics`.
- Tenant readiness gauges для alert rules доступны по `GET /api/metrics/tenants`.
- Метрики включают:
	- `app_http_requests_total` — счётчик HTTP запросов (method/path/status)
	- `app_http_request_duration_seconds` — histogram latency
	- `app_uptime_seconds` — uptime процесса
	- `app_tenant_products_total{tenant_slug="..."}` — количество товаров на tenant
	- `app_tenant_has_bot_token{tenant_slug="..."}` — готовность bot token
	- `app_tenant_has_admin_api_key{tenant_slug="..."}` — готовность admin key
	- `app_tenant_status_active{tenant_slug="..."}` — активность tenant
- Каждый HTTP ответ содержит `X-Request-ID`; если клиент не передал header, ID генерируется на сервере.

Проверка вручную:

```bash
curl -sS http://127.0.0.1:${WEB_API_PORT:-8000}/api/metrics | head -n 40
curl -sS http://127.0.0.1:${WEB_API_PORT:-8000}/api/metrics/tenants | head -n 40
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
- Alertmanager UI: `http://<host>:${ALERTMANAGER_PORT:-9093}`
- Grafana UI: `http://<host>:${GRAFANA_PORT:-3000}`
	- логин/пароль по умолчанию: `admin` / `admin`
	- dashboard уже подхватывается автоматически: **MLI Shop API Overview**

Готовые alert rules включают:

- `MLIWebAPIDown`
- `MLIWebAPIHigh5xxRate`
- `MLIWebAPISlowP95`
- `MLITenantMissingBotToken`
- `MLITenantMissingAdminAPIKey`
- `MLITenantEmptyCatalog`

Быстрая проверка scrape:

```bash
curl -sS http://127.0.0.1:${PROMETHEUS_PORT:-9090}/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health, scrapeUrl: .scrapeUrl}'
```

Reload конфигов мониторинга без перезапуска:

```bash
./scripts/reload_monitoring.sh
```

## Backup / Restore

Для production в проект добавлены боевые скрипты работы с PostgreSQL dump:

- backup: `./scripts/db_backup.sh`
- restore: `./scripts/db_restore.sh --file <dump>`
- backup drill: `./scripts/db_backup_drill.sh`

Примеры:

```bash
./scripts/db_backup.sh --env-file .env --label nightly
./scripts/db_backup.sh --env-file .env.flowers-shop --project-name mli-shop-flowers --label nightly
./scripts/db_backup_drill.sh --env-file .env
```

Дампы по умолчанию пишутся в `./backups/` и исключены из git.

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

## Telegram-команды владельца

Ниже перечислены команды, которые владелец магазина может выполнять прямо в Telegram.

Важно:

- большинство команд требуют owner-права в текущем tenant;
- команды, работающие с пользователями по Telegram ID, требуют, чтобы пользователь уже нажал `/start` в этом боте и попал в БД;
- для multi-tenant сценария предпочтительно использовать tenant-aware команды `/staff` и `/unstaff`.

### Управление ролями

- `/add_owner <telegram_id>`: назначить второго владельца в текущем tenant.
- `/remove_owner <telegram_id>`: снять роль владельца с пользователя. Главного владельца tenant снять этой командой нельзя.
- `/staff <telegram_id>`: назначить пользователя продавцом (`STAFF`) в текущем tenant.
- `/unstaff <telegram_id>`: снять роль продавца и вернуть пользователя в `CLIENT`.
- `/set_seller <telegram_id>`: назначить пользователя продавцом через owner/admin handler. Оставлена для совместимости, но для tenant-aware сценария лучше использовать `/staff`.

### Управление клиентами

- `/block <telegram_id>`: заблокировать пользователя.
- `/unblock <telegram_id>`: разблокировать пользователя.
- блокировка и разблокировка также доступны owner-кнопками из интерфейса поддержки клиента.

### AI и квоты

- `/ai_provider`: показать текущий AI provider и модель.
- `/ai_provider groq`: переключить AI на Groq.
- `/ai_provider deepseek`: переключить AI на DeepSeek.
- `/ai_provider deepseek deepseek-chat`: явно указать модель.
- `/ai_provider reset`: сбросить AI provider на значения из `.env`.
- `/gift <telegram_id> <amount>`: начислить пользователю дополнительные AI-запросы.
- `/ai_audit`: выгрузить TXT-аудит диалогов с AI.

### Промо и меню

- `/promo`: разослать промо-видео из `media/promo.mp4` всем получателям текущего tenant.
- `/owner`: открыть главное меню владельца.

### Сервисные команды

- `/resetdb`: запросить полную очистку БД магазина с одноразовым кодом подтверждения.
- `/confirm_resetdb <code>`: подтвердить очистку БД по коду из `/resetdb`.

### Минимальные примеры

```text
/add_owner 123456789
/staff 987654321
/block 987654321
/gift 987654321 10
/ai_provider deepseek
/resetdb
```