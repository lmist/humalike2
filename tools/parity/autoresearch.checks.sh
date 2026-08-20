#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/service"
HUMALIKE_DATABASE_URL="sqlite:///$(mktemp -u /tmp/parity-checks-XXXXXX).db" \
  "$ROOT/.venv/bin/python" -m pytest tests/ -q 2>&1 | tail -5
