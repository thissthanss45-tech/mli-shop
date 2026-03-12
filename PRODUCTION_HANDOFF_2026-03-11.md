# Production Handoff — 2026-03-11

## Итоговый статус

- Production runtime main: `green`
- Production runtime flowers: `green`
- Monitoring stack: `green`
- Public HTTPS: `green`
- Temporary smoke tenants: `cleaned`

## Что было доведено в этом финальном проходе

### 1. TLS / Nginx / Public HTTPS

Сделано:

- исправлен production TLS flow так, чтобы `nginx` мог стартовать до выпуска боевого сертификата;
- добавен bootstrap-certificate flow для первого запуска;
- `scripts/setup_tls.sh` переведён на `certbot --webroot`, чтобы ACME challenge проходил через работающий `nginx`;
- после успешного выпуска сертификат синхронизируется в канонический live-path, после чего `nginx` форсированно пересоздаётся уже в TLS-конфиге;
- основной systemd unit теперь поднимает и `nginx`, а не только app stack.

Фактическая проверка:

- публичный HTTPS health: `https://147.45.178.138.sslip.io/api/health`
- результат: `{"status":"ok","database":"connected","products":3}`
- сертификат:
  - issuer: `Let's Encrypt / E7`
  - notBefore: `2026-03-11 18:08:33 GMT`
  - notAfter: `2026-06-09 18:08:32 GMT`

### 2. Smoke cleanup

Перед очисткой в main runtime были найдены временные tenant-записи:

- `smoke-a-rotated-0311`
- `smoke-b-0311`

Перед удалением было подтверждено:

- 2 smoke-tenants;
- 1 связанный тестовый заказ;
- 4 товарные записи, привязанные к smoke-tenant данным.

Удаление выполнено транзакционно через PostgreSQL.

Проверка после удаления:

- `smoke_tenants = 0`
- `smoke_orders = 0`

Итоговый tenant inventory в main runtime:

- `default` → `147.45.178.138.sslip.io`
- `flowers-boutique`

### 3. Monitoring / Ops

Подтверждено на финальном снимке:

- `mli-shop-main.service` = `active`
- `mli-shop-flowers.service` = `active`
- `mli-shop-monitoring.service` = `active`

Monitoring endpoints:

- Prometheus: `9091`
- Alertmanager: `9094`
- Grafana: `3001`

Active Prometheus targets:

- `mli_tenant_metrics = up`
- `mli_web_api = up`
- `prometheus = up`

Уже ранее в этом сеансе подтверждено:

- backup dump был создан успешно;
- backup drill завершился успешно;
- `reload_monitoring.sh` работает корректно с runtime-портами из `.env`.

## Изменённые production-механизмы

- `docker-compose.yml`
  - `nginx` переведён на TLS-aware bootstrap flow через render script.
- `ops/systemd/mli-shop-main.service`
  - main runtime теперь управляет `nginx` вместе с `db/redis/rabbitmq/web_api/worker/bot`.
- `infra/nginx/render-nginx-config.sh`
  - выбирает HTTP-only или HTTPS template в зависимости от наличия cert files.
- `infra/nginx/templates/default.http.conf.tmpl`
  - HTTP bootstrap config для первого запуска и ACME webroot.
- `infra/nginx/templates/default.https.conf.tmpl`
  - production HTTPS reverse proxy config.
- `scripts/ensure_bootstrap_cert.sh`
  - создаёт временный self-signed cert для cold start.
- `scripts/setup_tls.sh`
  - выполняет webroot issuance и переключает `nginx` на боевой cert.

## Финальный checklist

- [x] Main runtime поднят под systemd.
- [x] Flowers runtime поднят под systemd.
- [x] Monitoring stack поднят под systemd.
- [x] Public HTTP доступен на `80/tcp`.
- [x] Public HTTPS доступен на `443/tcp`.
- [x] Реальный сертификат Let's Encrypt выпущен.
- [x] Reverse proxy отдаёт приложение через `nginx`.
- [x] Monitoring targets находятся в состоянии `up`.
- [x] Временные smoke tenants удалены.
- [x] Финальный production handoff документирован.

## Операционные замечания для handoff

- Сертификат уже боевой, но renewal automation нужно держать включённой через существующий `scripts/renew_tls.sh` и планировщик сервера.
- Monitoring в этом workspace использует не дефолтные хост-порты, а:
  - Prometheus `9091`
  - Alertmanager `9094`
  - Grafana `3001`
- Причина смещения портов: на сервере уже существует другой контейнер, занимающий `9090`.

## Результат handoff

На момент передачи:

- публичный домен отвечает по HTTPS;
- сертификат валиден и выдан Let's Encrypt;
- основной reverse proxy включён в systemd-подъём main runtime;
- временные smoke-данные удалены;
- основной production контур можно считать завершённым для текущего сервера.