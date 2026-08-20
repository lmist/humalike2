#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -z "${HUMALIKE_API_KEY:-}" ] && [ -f "$ROOT/../../.env" ]; then
  set -a
  . "$ROOT/../../.env"
  set +a
fi

exec /Users/lou/.nvm/versions/node/v24.18.0/bin/node "$ROOT/run.mjs"
