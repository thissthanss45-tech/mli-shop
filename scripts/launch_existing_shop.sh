#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE_NAME=".env"

if [[ ! -f "$ENV_FILE_NAME" ]]; then
  echo "Missing $ENV_FILE_NAME" >&2
  exit 1
fi

echo "Starting original shop on default compose project using $ENV_FILE_NAME..."
ENV_FILE="$ENV_FILE_NAME" docker compose --env-file "$ENV_FILE_NAME" up -d --build db redis rabbitmq web_api worker bot

echo
echo "Original shop start requested."
echo "Web API: http://127.0.0.1:8011"
echo "Admin:   http://127.0.0.1:8011/admin"