# Tenant Operations Runbook

## Назначение

Этот runbook описывает операционный цикл для нового магазина в multi-tenant SaaS версии MLI Shop:

- создать tenant;
- назначить owner;
- выдать tenant-specific admin API key;
- подключить домен и bot token;
- проверить storefront, web-admin, bot и worker;
- включить мониторинг.

## 1. Что должно быть готово заранее

Перед онбордингом нового магазина подготовьте:

- slug магазина, например `flowers-boutique`;
- публичный домен, например `flowers.example.com`;
- Telegram bot token для отдельного tenant;
- Telegram ID владельца магазина;
- доступ к верхнему `WEB_ADMIN_KEY`;
- доступ к docker compose окружению.

## 2. Создание нового tenant

Откройте админ-панель `/admin` и используйте блок `Онбординг нового магазина`.

Заполните поля:

- `Slug`
- `Название магазина`
- `Domain`
- `Bot token`
- `Owner TG ID`
- `Admin API key` (опционально)

Если `Admin API key` не указан, система сгенерирует его автоматически.

После создания tenant система:

- создаёт запись `Tenant`;
- создаёт дефолтные `TenantSettings`;
- создаёт или привязывает owner-пользователя;
- создаёт `TenantMembership` c ролью `owner`.

## 3. Первичная настройка магазина

После создания tenant:

1. выберите tenant в таблице магазинов;
2. загрузите `Настройки магазина`;
3. задайте:
   - storefront title;
   - кнопки меню;
   - welcome texts;
   - tenant-specific `admin_api_key`;
4. сохраните изменения.

Рекомендуется сразу проверить:

- `GET /api/admin/tenant-settings?tenant=<slug>`
- доступ в `/admin?tenant=<slug>` с tenant-specific Bearer key.

## 4. Домен и reverse proxy

Для production домен tenant должен вести на общий web stack. Tenant определяется через:

- query param `tenant=<slug>`;
- заголовок `X-Tenant-Slug`;
- домен из `Host` / `X-Forwarded-Host`.

Если используется доменное разделение, проверьте что reverse proxy:

- пробрасывает `Host`;
- пробрасывает `X-Forwarded-Host`;
- не затирает оригинальный hostname.

## 5. Bot и worker

У каждого магазина может быть собственный `bot_token`.

Проверьте:

- worker читает события и определяет tenant по bot token;
- уведомления уходят в правильный tenant context;
- AI/логирование не смешиваются между tenant.

После изменения bot token безопаснее перезапустить сервисы:

```bash
docker compose up -d bot worker web_api
```

## 6. Деплой стека

### Упрощённый сценарий: один активный Telegram-магазин

Для single-shop запуска используйте готовый launcher:

```bash
cd /root/mli_shop_project
chmod +x scripts/launch_tg_shop.sh scripts/launch_flower_shop.sh
./scripts/launch_flower_shop.sh --bot-token <TOKEN_FROM_BOTFATHER> --owner-id <YOUR_TG_ID>
```

Этот режим удобен, когда нужно быстро поднять один реальный магазин в Telegram без ручного provisioning через админку.

Основной запуск:

```bash
docker compose up -d --build
```

Мониторинг:

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
systemctl enable --now mli-shop-monitoring.service
```

Проверьте, что поднялись сервисы:

- `db`
- `redis`
- `rabbitmq`
- `bot`
- `worker`
- `web_api`
- `nginx`
- `prometheus`
- `alertmanager`
- `grafana`

## 7. Smoke-check нового tenant

Минимальный smoke после онбординга:

1. `GET /api/products?tenant=<slug>` возвращает каталог без чужих товаров.
2. `GET /api/admin/tenant-settings?tenant=<slug>` отвечает с tenant-specific key.
3. `/admin` открывается и даёт сохранить настройки магазина.
4. Telegram bot отвечает через нужный bot token.
5. Новый заказ появляется только в пределах tenant.
6. Worker обрабатывает AI/async сценарии в tenant-specific контексте.

Для полного прогона используйте также [MULTI_TENANT_SMOKE_CHECKLIST.md](MULTI_TENANT_SMOKE_CHECKLIST.md).

## 8. Мониторинг

После деплоя проверьте:

- `/metrics` у `web_api` доступен Prometheus;
- Prometheus видит target приложения;
- Grafana подключена к Prometheus datasource;
- есть базовые метрики по HTTP latency и request count.

Минимальный набор алертов, который стоит настроить:

- web_api недоступен;
- рост 5xx;
- резкий рост latency;
- недоступен RabbitMQ или Redis;
- worker не потребляет очередь.

В репозитории уже подготовлены:

- `infra/monitoring/prometheus/alerts.yml`
- `infra/monitoring/alertmanager/alertmanager.yml`
- `scripts/reload_monitoring.sh`

После изменения alert rules можно выполнить:

```bash
./scripts/reload_monitoring.sh
```

## 8.1 Backup / Restore

Для production обязательно должен выполняться регулярный backup drill.

Команды:

```bash
./scripts/db_backup.sh --env-file .env --label nightly
./scripts/db_backup.sh --env-file .env.flowers-shop --project-name mli-shop-flowers --label nightly
./scripts/db_backup_drill.sh --env-file .env
./scripts/db_backup_drill.sh --env-file .env.flowers-shop --project-name mli-shop-flowers
```

Restore:

```bash
./scripts/db_restore.sh --env-file .env --file ./backups/<dump>.dump
```

Рекомендуемый operational baseline:

- nightly backup для каждого runtime;
- ежедневный backup drill хотя бы на одном runtime;
- отдельное хранение backup вне сервера.

## 9. Ротация ключей

Можно ротировать tenant-specific `admin_api_key` из блока `Настройки магазина` кнопкой:

- `Сгенерировать новый admin API key`

После ротации:

- старый Bearer key становится невалидным;
- новый ключ нужно обновить в операционных секретах и у администраторов tenant.

## 10. Что делать при инциденте

Если tenant не открывается или отвечает чужими данными:

1. проверьте `tenant slug`, `domain` и `bot token`;
2. проверьте headers `Host` и `X-Forwarded-Host` на proxy;
3. проверьте, что запрос идёт с правильным Bearer key;
4. проверьте membership owner/staff в БД;
5. проверьте логи `web_api`, `bot`, `worker`;
6. выполните smoke-check только для проблемного tenant.

## 11. Операционные замечания

- Для каждого магазина лучше использовать отдельный Telegram bot token.
- Tenant-specific admin key нельзя шарить между магазинами.
- Domain-based routing удобнее для production, slug-based routing удобнее для smoke и диагностики.
- Перед массовым онбордингом магазинов стоит автоматизировать выдачу доменов, секретов и шаблонных storefront-настроек.
