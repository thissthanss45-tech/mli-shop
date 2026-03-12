#!/bin/sh
set -eu

: "${TLS_DOMAIN:?TLS_DOMAIN is required}"

CERT_DIR="/etc/letsencrypt/live/${TLS_DOMAIN}"
TEMPLATE_HTTP="/etc/nginx/templates/default.http.conf.tmpl"
TEMPLATE_HTTPS="/etc/nginx/templates/default.https.conf.tmpl"
TARGET_CONF="/etc/nginx/conf.d/default.conf"

if [ -f "${CERT_DIR}/fullchain.pem" ] && [ -f "${CERT_DIR}/privkey.pem" ]; then
  TEMPLATE="${TEMPLATE_HTTPS}"
else
  TEMPLATE="${TEMPLATE_HTTP}"
fi

envsubst '${TLS_DOMAIN}' < "${TEMPLATE}" > "${TARGET_CONF}"

exec nginx -g 'daemon off;'