#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"

if [[ -f "${ENV_FILE}" ]]; then
	set -a
	. "${ENV_FILE}"
	set +a
fi

PROM_URL="${PROMETHEUS_URL:-http://127.0.0.1:${PROMETHEUS_PORT:-9090}}"
ALERT_URL="${ALERTMANAGER_URL:-http://127.0.0.1:${ALERTMANAGER_PORT:-9093}}"

echo "Reloading Prometheus config at ${PROM_URL} ..."
curl -fsS -X POST "${PROM_URL}/-/reload" >/dev/null

echo "Reloading Alertmanager config at ${ALERT_URL} ..."
curl -fsS -X POST "${ALERT_URL}/-/reload" >/dev/null

echo "Monitoring config reloaded"