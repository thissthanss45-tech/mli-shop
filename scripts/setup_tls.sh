#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <domain> <email>" >&2
  echo "Example: $0 shop.example.com admin@shop.example.com" >&2
  exit 1
fi

DOMAIN="$1"
EMAIL="$2"

if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
  echo "ERROR: domain and email are required" >&2
  exit 1
fi

cd "$(dirname "$0")/.."

mkdir -p certbot/conf certbot/www

echo "[1/4] Starting core services (without nginx/certbot)..."
docker compose up -d db redis rabbitmq bot worker web_api

echo "[2/4] Requesting Let's Encrypt certificate for $DOMAIN ..."
# stop nginx if it is running to free port 80 for standalone challenge
if docker compose ps nginx --status running >/dev/null 2>&1; then
  docker compose stop nginx || true
fi

docker compose run --rm --service-ports \
  -e TLS_DOMAIN="$DOMAIN" \
  certbot certonly \
  --standalone \
  --preferred-challenges http \
  --non-interactive \
  --agree-tos \
  --email "$EMAIL" \
  -d "$DOMAIN"

echo "[3/4] Starting nginx with TLS config..."
TLS_DOMAIN="$DOMAIN" docker compose up -d nginx

echo "[4/4] Done. Health check:"
curl -sS -I "https://$DOMAIN/api/health" || true

echo "TLS setup finished for $DOMAIN"
