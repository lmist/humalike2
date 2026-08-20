#!/usr/bin/env bash
# Pre-push is advisory: do not block, but print bead hygiene.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
export PATH="$ROOT/bin:$PATH"
[[ -x "$ROOT/bin/bd" && -f "$ROOT/.beads/metadata.json" ]] || exit 0
echo "human: in_progress beads at push time:" >&2
"$ROOT/bin/bd" list --status in_progress 2>/dev/null | head -20 >&2 || true
exit 0
