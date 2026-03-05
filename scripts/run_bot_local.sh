#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if command -v docker >/dev/null 2>&1; then
  if docker compose ps bot --status running >/dev/null 2>&1; then
    echo "ERROR: docker compose service 'bot' is already running." >&2
    echo "Stop it first to avoid TelegramConflictError (double getUpdates)." >&2
    echo "Command: docker compose stop bot" >&2
    exit 1
  fi
fi

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found in project root" >&2
  exit 1
fi

set -a
source .env
set +a

if [[ -z "${BOT_TOKEN:-}" || -z "${OWNER_ID:-}" ]]; then
  echo "ERROR: BOT_TOKEN/OWNER_ID are required in .env" >&2
  exit 1
fi

DB_URL_EFFECTIVE="${DB_URL:-}"
if [[ -z "$DB_URL_EFFECTIVE" ]]; then
  echo "ERROR: DB_URL is not set in .env" >&2
  exit 1
fi

if [[ "$DB_URL_EFFECTIVE" == *"@db/"* ]]; then
  DB_IP="$(docker inspect mli_shop_project-db-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null || true)"
  if [[ -n "$DB_IP" ]]; then
    DB_URL_EFFECTIVE="${DB_URL_EFFECTIVE/@db\//@${DB_IP}/}"
    echo "INFO: DB host 'db' replaced with container IP ${DB_IP} for local bot run"
  else
    echo "WARN: Could not resolve mli_shop_project-db-1 IP. Keeping original DB_URL"
  fi
fi

export DB_URL="$DB_URL_EFFECTIVE"

echo "INFO: Starting Telegram bot (shop.py)"
exec python3 shop.py
