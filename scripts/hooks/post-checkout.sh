#!/usr/bin/env bash
# After checkout, remind the agent what is ready.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
export PATH="$ROOT/bin:$PATH"
[[ -x "$ROOT/bin/bd" && -f "$ROOT/.beads/metadata.json" ]] || exit 0
echo "human: bd ready (post-checkout)" >&2
"$ROOT/bin/bd" ready 2>/dev/null | head -20 >&2 || true
exit 0
