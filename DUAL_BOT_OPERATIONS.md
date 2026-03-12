# Dual Bot Operations

## Active stacks

- Main shop: default Docker Compose project, web API on port `8011`, env file `.env`.
- Flower shop: Docker Compose project `mli-shop-flowers`, web API on port `8010`, env file `.env.flowers-shop`.
- Both operational commands should pass `ENV_FILE=...` because `docker-compose.yml` uses `${ENV_FILE}` inside service `env_file` sections.

## Manual management

### Main shop

Start or recreate stack:

```bash
cd /root/mli_shop_project
ENV_FILE=.env docker compose --env-file .env up -d db redis rabbitmq web_api worker bot
```

Stop stack:

```bash
cd /root/mli_shop_project
ENV_FILE=.env docker compose --env-file .env stop bot worker web_api rabbitmq redis db
```

Logs:

```bash
cd /root/mli_shop_project
ENV_FILE=.env docker compose --env-file .env logs -f bot
ENV_FILE=.env docker compose --env-file .env logs -f web_api
```

Health:

```bash
curl http://127.0.0.1:8011/api/health
```

### Flower shop

Start or recreate stack:

```bash
cd /root/mli_shop_project
ENV_FILE=.env.flowers-shop docker compose --env-file .env.flowers-shop -p mli-shop-flowers up -d db redis rabbitmq web_api worker bot
```

Stop stack:

```bash
cd /root/mli_shop_project
ENV_FILE=.env.flowers-shop docker compose --env-file .env.flowers-shop -p mli-shop-flowers stop bot worker web_api rabbitmq redis db
```

Logs:

```bash
cd /root/mli_shop_project
ENV_FILE=.env.flowers-shop docker compose --env-file .env.flowers-shop -p mli-shop-flowers logs -f bot
ENV_FILE=.env.flowers-shop docker compose --env-file .env.flowers-shop -p mli-shop-flowers logs -f web_api
```

Health:

```bash
curl http://127.0.0.1:8010/api/health
curl 'http://127.0.0.1:8010/api/health/tenant?tenant=flowers-boutique'
```

## systemd

Unit templates are stored in `ops/systemd/` and installed as:

- `mli-shop-main.service`
- `mli-shop-flowers.service`

Main commands:

```bash
systemctl status mli-shop-main.service
systemctl restart mli-shop-main.service
systemctl status mli-shop-flowers.service
systemctl restart mli-shop-flowers.service
```

## Notes

- `/api/health` on the flower stack shows default-tenant counters and may report `products: 0`.
- Tenant-specific readiness for the flower store should be checked via `/api/health/tenant?tenant=flowers-boutique`.
- `nginx` is intentionally excluded from the dual-bot operational commands because only one stack can own ports `80/443` on this host.