#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a
source "$ROOT/.env"
set +a

exec /Users/lou/.nvm/versions/node/v24.18.0/bin/node "$ROOT/tests/intelligence/run.mjs"
