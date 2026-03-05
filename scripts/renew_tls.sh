#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <domain>" >&2
  exit 1
fi

DOMAIN="$1"
cd "$(dirname "$0")/.."

echo "Renewing certificates..."
docker compose run --rm certbot renew --webroot -w /var/www/certbot

echo "Reloading nginx..."
TLS_DOMAIN="$DOMAIN" docker compose exec -T nginx nginx -s reload

echo "Done"
