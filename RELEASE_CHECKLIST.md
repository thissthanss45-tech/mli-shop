# Release Checklist (mli_shop_project)

Дата: 2026-02-17
Окружение: Production
Ответственный: Owner/DevOps

## 1) Pre-Release (до выката)

- [ ] Проверить актуальность `.env` (BOT_TOKEN, DB_URL, REDIS_URL, RABBITMQ_URL, webhook/polling настройки).
- [ ] Убедиться, что доступны ресурсы: Postgres, Redis, RabbitMQ.
- [ ] Проверить свободное место на диске и ротацию логов.
- [ ] Убедиться, что миграции БД применяются без ошибок.
- [ ] Проверить, что контейнерные образы собираются без ошибок.

Команды:

- `docker compose config`
- `docker compose build bot worker`
- `docker compose run --rm bot alembic -c /app/alembic.ini upgrade head`

## 2) Backup / Safety Point

- [ ] Снять backup БД перед релизом.
- [ ] Зафиксировать текущую рабочую версию образов (tag/sha).
- [ ] Сохранить последний рабочий docker-compose и env.

Пример backup:

- `docker compose exec -T db pg_dump -U shop_user -d shop_db > backup_$(date +%F_%H-%M).sql`

## 3) Deploy

- [ ] Выполнить обновление сервисов.
- [ ] Убедиться, что bot и worker в статусе Up.

Команды:

- `docker compose up -d --build bot worker`
- `docker compose ps`
- `docker compose logs --no-color --tail=100 bot worker`

## 4) Smoke Test (обязательно)

- [ ] Клиент: AI карточка товара показывает бренд.
- [ ] Клиент: checkout по кнопке «Оформить заказ» работает при непустой корзине.
- [ ] Owner/Склад: «Закупка» считает только приходы (manual_add), не уменьшается из-за продаж.
- [ ] Owner/Склад: карточка из «Закупки» показывает «Закуплено за период: N шт».
- [ ] Owner/Склад: клавиатура дашборда 3 ряда по 2 кнопки + нижняя «В меню».
- [ ] Owner/Склад: в «Скачать отчет» нет годов меньше 2026.

## 5) Monitoring (первые 30-60 минут)

- [ ] Проверять ошибки в логах bot/worker каждые 5-10 минут.
- [ ] Контролировать время ответа callback и количество исключений.
- [ ] Проверить, что нет всплеска ошибок БД/Redis/RabbitMQ.

Команды:

- `docker compose logs --no-color --tail=200 -f bot`
- `docker compose logs --no-color --tail=200 -f worker`

## 6) Rollback Plan

Триггеры отката:

- Критичный функционал недоступен > 5 минут.
- Ошибки checkout/заказов повторяются.
- Массовые 5xx/исключения в bot/worker.

Шаги отката:

- [ ] Остановить текущие сервисы: `docker compose stop bot worker`
- [ ] Вернуть предыдущие образы/конфиги.
- [ ] Поднять стабильную версию: `docker compose up -d bot worker`
- [ ] Проверить smoke-test по 3 ключевым сценариям.

## 7) Release Sign-off

- [ ] Тех. проверка пройдена (Dev).
- [ ] Бизнес-сценарии подтверждены (Owner).
- [ ] Логи стабильны 30+ минут.
- [ ] Релиз принят.

Подпись/дата:

- Dev: ____________________
- Owner: __________________
