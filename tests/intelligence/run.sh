#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [ -z "${HUMALIKE_API_KEY:-}" ] && [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

NODE_BIN="${NODE:-$(command -v node || true)}"
if [ -z "$NODE_BIN" ] && [ -x /Users/lou/.nvm/versions/node/v24.18.0/bin/node ]; then
  NODE_BIN=/Users/lou/.nvm/versions/node/v24.18.0/bin/node
fi
if [ -z "$NODE_BIN" ]; then
  echo "node not found; set NODE=/path/to/node" >&2
  exit 2
fi

exec "$NODE_BIN" "$ROOT/tests/intelligence/run.mjs"
