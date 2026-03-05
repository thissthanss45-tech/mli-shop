#!/usr/bin/env bash
set -euo pipefail

BASE_ENV=".env"

if [[ ! -f "$BASE_ENV" ]]; then
  echo "ERROR: $BASE_ENV not found. Run this script from the project root." >&2
  exit 1
fi

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
  shift || true
fi

load_var() {
  local name="$1"
  local value
  value=$(grep -E "^${name}=" "$BASE_ENV" | head -n1 | cut -d= -f2- || true)
  printf '%s' "$value"
}

# Read keys and shared settings from base .env
GROQ_API_KEY=$(load_var "GROQ_API_KEY")
DEEPSEEK_API_KEY=$(load_var "DEEPSEEK_API_KEY")
DB_URL=$(load_var "DB_URL")
REDIS_URL=$(load_var "REDIS_URL")
RABBITMQ_URL=$(load_var "RABBITMQ_URL")
OWNER_ID=$(load_var "OWNER_ID")
ADMIN_IDS=$(load_var "ADMIN_IDS")
AI_CLIENT_START_QUOTA=$(load_var "AI_CLIENT_START_QUOTA")
AI_CLIENT_BONUS_QUOTA=$(load_var "AI_CLIENT_BONUS_QUOTA")
MAX_PHOTOS_PER_MODEL=$(load_var "MAX_PHOTOS_PER_MODEL")
TIMEZONE=$(load_var "TIMEZONE")
GROQ_MODEL=$(load_var "GROQ_MODEL")
DEEPSEEK_MODEL=$(load_var "DEEPSEEK_MODEL")

echo "Client name правила: только латиница/цифры/символы '_' или '-'. Пример: flowers"
read -r -p "Client name (e.g. flowers): " CLIENT_NAME
if [[ -z "$CLIENT_NAME" ]]; then
  echo "ERROR: client name is required" >&2
  exit 1
fi

# allow only safe characters for project/db names
if [[ ! "$CLIENT_NAME" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "ERROR: client name must contain only letters, digits, '_' or '-'" >&2
  exit 1
fi

# normalize to lower-case for project/db identifiers
CLIENT_NAME_LOWER=$(printf '%s' "$CLIENT_NAME" | tr 'A-Z' 'a-z')

echo "Bot token пример: 123456789:ABCDEF..."
read -r -p "Bot token (BotFather): " BOT_TOKEN
if [[ -z "$BOT_TOKEN" ]]; then
  echo "ERROR: bot token is required" >&2
  exit 1
fi

echo "System prompt пример: Ты опытный консультант магазина."
read -r -p "System prompt (role): " SYSTEM_PROMPT
if [[ -z "$SYSTEM_PROMPT" ]]; then
  echo "ERROR: system prompt is required" >&2
  exit 1
fi

echo "Select AI provider:"
echo "  1 - Groq (Speed)"
echo "  2 - DeepSeek (Cost)"
read -r -p "Choice [1/2]: " AI_CHOICE
case "$AI_CHOICE" in
  1) AI_PROVIDER="groq" ;;
  2) AI_PROVIDER="deepseek" ;;
  *)
    echo "ERROR: invalid choice" >&2
    exit 1
    ;;
esac

# Validate that required key exists for chosen provider
if [[ "$AI_PROVIDER" == "groq" && -z "$GROQ_API_KEY" ]]; then
  echo "ERROR: GROQ_API_KEY is missing in $BASE_ENV for provider 'groq'" >&2
  exit 1
fi
if [[ "$AI_PROVIDER" == "deepseek" && -z "$DEEPSEEK_API_KEY" ]]; then
  echo "ERROR: DEEPSEEK_API_KEY is missing in $BASE_ENV for provider 'deepseek'" >&2
  exit 1
fi

read -r -p "Button: Catalog (default \"📦 Каталог\"): " BTN_CATALOG
read -r -p "Button: Cart (default \"🛒 Корзина\"): " BTN_CART
read -r -p "Button: Profile (default \"👤 Профиль\"): " BTN_PROFILE

BTN_CATALOG=${BTN_CATALOG:-"📦 Каталог"}
BTN_CART=${BTN_CART:-"🛒 Корзина"}
BTN_PROFILE=${BTN_PROFILE:-"👤 Профиль"}

TARGET_ENV=".env.${CLIENT_NAME_LOWER}"
DB_NAME="${CLIENT_NAME_LOWER}_db"
ESCAPED_PROMPT=$(printf '%s' "$SYSTEM_PROMPT" | sed 's/\\/\\\\/g; s/"/\\"/g')

cat > "$TARGET_ENV" <<EOF
BOT_TOKEN=${BOT_TOKEN}
SYSTEM_PROMPT="${ESCAPED_PROMPT}"
AI_PROVIDER=${AI_PROVIDER}
GROQ_API_KEY=${GROQ_API_KEY}
DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
GROQ_MODEL=${GROQ_MODEL}
DEEPSEEK_MODEL=${DEEPSEEK_MODEL}

OWNER_ID=${OWNER_ID}
ADMIN_IDS=${ADMIN_IDS}

DB_URL=${DB_URL}
REDIS_URL=${REDIS_URL}
RABBITMQ_URL=${RABBITMQ_URL}
DB_NAME=${DB_NAME}

BUTTON_CATALOG=${BTN_CATALOG}
BUTTON_CART=${BTN_CART}
BUTTON_PROFILE=${BTN_PROFILE}

AI_CLIENT_START_QUOTA=${AI_CLIENT_START_QUOTA}
AI_CLIENT_BONUS_QUOTA=${AI_CLIENT_BONUS_QUOTA}
MAX_PHOTOS_PER_MODEL=${MAX_PHOTOS_PER_MODEL}
TIMEZONE=${TIMEZONE}
EOF

echo "[INFO] Generated env file: ${TARGET_ENV}"
echo "[INFO] Docker project name: ${CLIENT_NAME_LOWER}"

echo "Running: docker-compose -p ${CLIENT_NAME_LOWER} --env-file ${TARGET_ENV} up -d --build"
if [[ "$DRY_RUN" == true ]]; then
  echo "[DRY-RUN] Skipping docker-compose execution."
else
  docker-compose -p "${CLIENT_NAME_LOWER}" --env-file "${TARGET_ENV}" up -d --build
fi
