#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE_NAME=".env"
PROJECT_NAME_VALUE=""
KEEP_FILES="false"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/db_backup_drill.sh [--env-file .env] [--project-name mli-shop-flowers] [--keep-files]

Creates a backup and validates that pg_restore can read the archive.
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
    --keep-files)
      KEEP_FILES="true"
      shift
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

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

BACKUP_OUTPUT="$(./scripts/db_backup.sh --env-file "$ENV_FILE_NAME" ${PROJECT_NAME_VALUE:+--project-name "$PROJECT_NAME_VALUE"} --output-dir "$TMP_DIR" --label drill)"
DUMP_FILE="$(printf '%s\n' "$BACKUP_OUTPUT" | tail -n 1)"

if [[ ! -f "$DUMP_FILE" ]]; then
  echo "Backup drill failed: dump file missing" >&2
  exit 1
fi

cat "$DUMP_FILE" | compose_cmd exec -T db sh -lc 'cat >/tmp/backup-drill.dump && pg_restore -l /tmp/backup-drill.dump >/dev/null && rm -f /tmp/backup-drill.dump'

if [[ "$KEEP_FILES" == "true" ]]; then
  FINAL_DIR="$ROOT_DIR/backups"
  mkdir -p "$FINAL_DIR"
  cp "$TMP_DIR"/* "$FINAL_DIR"/
fi

echo "Backup drill passed"