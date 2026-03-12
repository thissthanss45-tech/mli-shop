#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE_NAME=".env"
PROJECT_NAME_VALUE=""
OUTPUT_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
LABEL_VALUE="manual"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/db_backup.sh [--env-file .env] [--project-name mli-shop-flowers] [--output-dir ./backups] [--label nightly]

Creates PostgreSQL custom-format dump from the running db container and writes:
  - *.dump
  - *.sha256
  - *.meta
EOF
}

compose_cmd() {
  if [[ -n "$PROJECT_NAME_VALUE" ]]; then
    ENV_FILE="$ENV_FILE_NAME" docker compose --env-file "$ENV_FILE_NAME" -p "$PROJECT_NAME_VALUE" "$@"
  else
    ENV_FILE="$ENV_FILE_NAME" docker compose --env-file "$ENV_FILE_NAME" "$@"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      ENV_FILE_NAME="$2"
      shift 2
      ;;
    --project-name)
      PROJECT_NAME_VALUE="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --label)
      LABEL_VALUE="$2"
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

if [[ ! -f "$ENV_FILE_NAME" ]]; then
  echo "Missing env file: $ENV_FILE_NAME" >&2
  exit 1
fi

set -a
source "$ENV_FILE_NAME"
set +a

mkdir -p "$OUTPUT_DIR"

STACK_NAME="${PROJECT_NAME_VALUE:-main}"
STAMP="$(date +%Y%m%d-%H%M%S)"
PREFIX="${OUTPUT_DIR%/}/${STACK_NAME}-${LABEL_VALUE}-${STAMP}"
DUMP_FILE="${PREFIX}.dump"
SHA_FILE="${PREFIX}.sha256"
META_FILE="${PREFIX}.meta"

echo "Creating backup: $DUMP_FILE"
compose_cmd exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$DUMP_FILE"

sha256sum "$DUMP_FILE" > "$SHA_FILE"
{
  echo "created_at=$(date --iso-8601=seconds)"
  echo "env_file=$ENV_FILE_NAME"
  echo "project_name=${PROJECT_NAME_VALUE:-default}"
  echo "db_name=$POSTGRES_DB"
  echo "db_user=$POSTGRES_USER"
  echo "label=$LABEL_VALUE"
} > "$META_FILE"

echo "Backup completed"
echo "$DUMP_FILE"