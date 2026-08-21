#!/bin/sh
# Start the shadow proxy: serves from the local recreation, mirrors to production.
# Reads the production key from <repo>/.env (HUMALIKE_API_KEY) unless
# SHADOW_PROD_KEY is already set. Usage: tools/shadow/run.sh [--no-mirror]
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if [ -z "${SHADOW_PROD_KEY:-}" ] && [ -f "$ROOT/.env" ]; then
  SHADOW_PROD_KEY=$(sed -n 's/^HUMALIKE_API_KEY=//p' "$ROOT/.env" | head -1)
  export SHADOW_PROD_KEY
fi
[ "${1:-}" = "--no-mirror" ] && export SHADOW_MIRROR=0
if [ ! -x "$ROOT/service/.venv/bin/python" ]; then
  echo "service venv missing: (cd service && uv venv .venv && uv pip install -e '.[dev]')" >&2
  exit 2
fi
exec "$ROOT/service/.venv/bin/python" "$ROOT/tools/shadow/shadow_proxy.py"
