#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE_NAME=".env"
PROJECT_NAME_VALUE=""
DUMP_FILE=""
AUTO_CONFIRM="false"
RESTART_APPS="true"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/db_restore.sh --file ./backups/backup.dump [--env-file .env] [--project-name mli-shop-flowers] [--yes] [--no-restart]

Restores PostgreSQL dump into the target stack.
The script stops app services, recreates the database and restores the dump.
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
    --file)
      DUMP_FILE="$2"
      shift 2
      ;;
    --yes)
      AUTO_CONFIRM="true"
      shift
      ;;
    --no-restart)
      RESTART_APPS="false"
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

if [[ ! -f "$ENV_FILE_NAME" ]]; then
  echo "Missing env file: $ENV_FILE_NAME" >&2
  exit 1
fi

if [[ -z "$DUMP_FILE" || ! -f "$DUMP_FILE" ]]; then
  echo "Restore file not found: $DUMP_FILE" >&2
  exit 1
fi

set -a
source "$ENV_FILE_NAME"
set +a

if [[ "$AUTO_CONFIRM" != "true" ]]; then
  echo "About to restore $DUMP_FILE into stack ${PROJECT_NAME_VALUE:-default} / db ${POSTGRES_DB}."
  read -r -p "Type RESTORE to continue: " ANSWER
  if [[ "$ANSWER" != "RESTORE" ]]; then
    echo "Restore cancelled"
    exit 1
  fi
fi

echo "Stopping app services..."
compose_cmd stop bot worker web_api || true

echo "Recreating database $POSTGRES_DB ..."
compose_cmd exec -T db psql -U "$POSTGRES_USER" -d postgres <<EOF
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${POSTGRES_DB}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS ${POSTGRES_DB};
CREATE DATABASE ${POSTGRES_DB};
EOF

echo "Restoring dump..."
cat "$DUMP_FILE" | compose_cmd exec -T db sh -lc "cat >/tmp/restore.dump && pg_restore -U '$POSTGRES_USER' -d '$POSTGRES_DB' --clean --if-exists --no-owner /tmp/restore.dump && rm -f /tmp/restore.dump"

if [[ "$RESTART_APPS" == "true" ]]; then
  echo "Starting app services..."
  compose_cmd up -d web_api worker bot
fi

echo "Restore completed"