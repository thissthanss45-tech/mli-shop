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
BOOTSTRAP_DIR="certbot/conf/live/${DOMAIN}"
BOOTSTRAP_MARKER="${BOOTSTRAP_DIR}/.bootstrap"

echo "[1/5] Ensuring bootstrap certificate for $DOMAIN ..."
./scripts/ensure_bootstrap_cert.sh "$DOMAIN"

echo "[2/5] Starting core services and HTTP reverse proxy ..."
TLS_DOMAIN="$DOMAIN" docker compose up -d db redis rabbitmq bot worker web_api nginx

echo "[3/5] Requesting Let's Encrypt certificate for $DOMAIN ..."
if [[ -f "${BOOTSTRAP_MARKER}" ]]; then
  rm -rf "${BOOTSTRAP_DIR}"
fi

docker compose run --rm \
  -e TLS_DOMAIN="$DOMAIN" \
  certbot certonly \
  --webroot \
  --webroot-path /var/www/certbot \
  --non-interactive \
  --agree-tos \
  --email "$EMAIL" \
  --keep-until-expiring \
  -d "$DOMAIN"

LATEST_CERT_DIR="$(find certbot/conf/live -maxdepth 1 -mindepth 1 -type d -name "${DOMAIN}*" | sort | tail -n 1)"

if [[ -n "${LATEST_CERT_DIR}" ]]; then
  mkdir -p "${BOOTSTRAP_DIR}"
  cp "${LATEST_CERT_DIR}/fullchain.pem" "${BOOTSTRAP_DIR}/fullchain.pem"
  cp "${LATEST_CERT_DIR}/privkey.pem" "${BOOTSTRAP_DIR}/privkey.pem"
  rm -f "${BOOTSTRAP_MARKER}"
fi

echo "[4/5] Reloading nginx with issued certificate..."
TLS_DOMAIN="$DOMAIN" docker compose up -d --force-recreate nginx

echo "[5/5] Done. Health check:"
curl -sS -I "https://$DOMAIN/api/health" || true

echo "TLS setup finished for $DOMAIN"
