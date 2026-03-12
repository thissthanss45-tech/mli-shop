#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <domain>" >&2
  exit 1
fi

DOMAIN="$1"
CERT_DIR="certbot/conf/live/${DOMAIN}"
FULLCHAIN_PATH="${CERT_DIR}/fullchain.pem"
PRIVKEY_PATH="${CERT_DIR}/privkey.pem"
BOOTSTRAP_MARKER="${CERT_DIR}/.bootstrap"

if [[ -s "${FULLCHAIN_PATH}" && -s "${PRIVKEY_PATH}" ]]; then
  echo "Bootstrap certificate already present for ${DOMAIN}"
  exit 0
fi

mkdir -p "${CERT_DIR}"

openssl req \
  -x509 \
  -nodes \
  -newkey rsa:2048 \
  -days 1 \
  -subj "/CN=${DOMAIN}" \
  -keyout "${PRIVKEY_PATH}" \
  -out "${FULLCHAIN_PATH}" >/dev/null 2>&1

touch "${BOOTSTRAP_MARKER}"

echo "Bootstrap self-signed certificate created for ${DOMAIN}"