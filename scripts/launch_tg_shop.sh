#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/launch_tg_shop.sh \
    --bot-token <telegram_bot_token> \
    --owner-id <telegram_user_id> \
    [--slug flowers-boutique] \
    [--title "Flowers Boutique"] \
    [--preset flowers] \
    [--domain flowers.example.com] \
    [--env-file .env.flowers-shop]

This launcher is designed for one active Telegram bot process per shop.
It will:
  1. create an env file if needed,
  2. build app images,
  3. start db/redis/rabbitmq,
  4. bootstrap the tenant with preset data,
  5. start web_api/worker/bot.
EOF
}

BOT_TOKEN=""
OWNER_ID=""
SLUG="flowers-boutique"
TITLE="Flowers Boutique"
PRESET="flowers"
DOMAIN=""
ENV_FILE_NAME=".env.flowers-shop"
WEB_API_PORT_VALUE="8010"
PROJECT_NAME_VALUE=""

compose_cmd() {
  if [[ -n "$PROJECT_NAME_VALUE" ]]; then
    ENV_FILE="$ENV_FILE_NAME" docker compose --env-file "$ENV_FILE_NAME" -p "$PROJECT_NAME_VALUE" "$@"
  else
    ENV_FILE="$ENV_FILE_NAME" docker compose --env-file "$ENV_FILE_NAME" "$@"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bot-token)
      BOT_TOKEN="$2"
      shift 2
      ;;
    --owner-id)
      OWNER_ID="$2"
      shift 2
      ;;
    --slug)
      SLUG="$2"
      shift 2
      ;;
    --title)
      TITLE="$2"
      shift 2
      ;;
    --preset)
      PRESET="$2"
      shift 2
      ;;
    --domain)
      DOMAIN="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE_NAME="$2"
      shift 2
      ;;
    --web-port)
      WEB_API_PORT_VALUE="$2"
      shift 2
      ;;
    --project-name)
      PROJECT_NAME_VALUE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$BOT_TOKEN" || -z "$OWNER_ID" ]]; then
  echo "--bot-token and --owner-id are required" >&2
  usage
  exit 1
fi

if ! [[ "$OWNER_ID" =~ ^[0-9]+$ ]]; then
  echo "--owner-id must be a numeric Telegram user id" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE_NAME" ]]; then
  WEB_ADMIN_KEY="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"
  cat > "$ENV_FILE_NAME" <<EOF
BOT_TOKEN=$BOT_TOKEN
OWNER_ID=$OWNER_ID
ADMIN_IDS=$OWNER_ID

POSTGRES_USER=shop_user
POSTGRES_PASSWORD=change_me_in_production
POSTGRES_DB=shop_db
DB_URL=postgresql+asyncpg://shop_user:change_me_in_production@db/shop_db

REDIS_URL=redis://redis:6379/0

RABBITMQ_USER=mli_shop
RABBITMQ_PASS=change_me_in_production
RABBITMQ_URL=amqp://mli_shop:change_me_in_production@rabbitmq:5672/

WEB_ADMIN_KEY=$WEB_ADMIN_KEY
CORS_ORIGINS=http://localhost,http://localhost:8000
TIMEZONE=Europe/Moscow
WEB_API_PORT=$WEB_API_PORT_VALUE
AI_PROVIDER=groq
GROQ_API_KEY=disabled-placeholder
DEEPSEEK_API_KEY=disabled-placeholder
EOF
  if [[ -n "$DOMAIN" ]]; then
    printf 'TLS_DOMAIN=%s\n' "$DOMAIN" >> "$ENV_FILE_NAME"
  fi
  echo "Created $ENV_FILE_NAME"
else
  echo "Using existing env file $ENV_FILE_NAME"
fi

echo "Building application images..."
compose_cmd build bot worker web_api

echo "Starting infrastructure services..."
compose_cmd up -d db redis rabbitmq

BOOTSTRAP_CMD="alembic -c /app/alembic.ini upgrade head && python scripts/bootstrap_telegram_shop.py --slug '$SLUG' --title '$TITLE' --preset '$PRESET' --bot-token '$BOT_TOKEN' --owner-id '$OWNER_ID'"
if [[ -n "$DOMAIN" ]]; then
  BOOTSTRAP_CMD+=" --domain '$DOMAIN'"
fi

echo "Bootstrapping tenant '$SLUG' with preset '$PRESET'..."
compose_cmd run --rm web_api sh -lc "$BOOTSTRAP_CMD"

echo "Starting application services..."
compose_cmd up -d web_api worker bot

echo "Waiting for web_api health on port $WEB_API_PORT_VALUE..."
for _ in {1..30}; do
  if curl -fsS "http://127.0.0.1:${WEB_API_PORT_VALUE}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo
echo "Telegram shop is ready to verify."
echo "Admin panel: http://127.0.0.1:${WEB_API_PORT_VALUE}/admin"
echo "Swagger:     http://127.0.0.1:${WEB_API_PORT_VALUE}/docs"
echo "Tenant smoke: curl -s 'http://127.0.0.1:${WEB_API_PORT_VALUE}/api/health/tenant?tenant=$SLUG'"
echo "Tenant metrics: curl -s http://127.0.0.1:${WEB_API_PORT_VALUE}/api/metrics/tenants | grep '$SLUG'"
echo
echo "Next: open your bot in Telegram and send /start from owner TG ID $OWNER_ID"