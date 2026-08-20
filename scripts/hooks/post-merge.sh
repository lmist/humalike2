#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
export PATH="$ROOT/bin:$PATH"
[[ -x "$ROOT/bin/bd" && -f "$ROOT/.beads/metadata.json" ]] || exit 0
"$ROOT/bin/bd" ready 2>/dev/null | head -20 >&2 || true
exit 0
