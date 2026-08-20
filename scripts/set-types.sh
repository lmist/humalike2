#!/usr/bin/env bash
# Register project-specific issue types (idempotent). Built-ins (task, bug,
# feature, chore, epic, decision, spike, story, milestone) come from `bd types`.
#   conformance — a live-suite run record against a target (spec/08 gate)
#   question    — a spec/08 open question being resolved
# Formula steps must still use built-in types; customs are for `bd create -t`.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$ROOT/bin:$PATH"
CUSTOM='["conformance","question"]'
current="$(bin/bd config get types.custom 2>/dev/null || true)"
if [[ "$current" == *conformance* && "$current" == *question* ]]; then
  echo "set-types: types.custom already set: $current"
  exit 0
fi
bin/bd config set types.custom "$CUSTOM"
echo "set-types: types.custom = $CUSTOM"
