#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec "$ROOT_DIR/scripts/launch_tg_shop.sh" \
  --project-name mli-shop-flowers \
  --preset flowers \
  --slug flowers-boutique \
  --title "Flowers Boutique" \
  "$@"