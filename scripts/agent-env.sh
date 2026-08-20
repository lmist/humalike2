#!/usr/bin/env bash
# Agent-host session hook. Puts <repo>/bin first on PATH so every `bd` an
# agent runs is the vendored build, and prints a one-line orientation.
#
# Claude Code: wired as a SessionStart hook in .claude/settings.json; when
#   $CLAUDE_ENV_FILE is set, the export is persisted for the whole session.
# Other hosts: `eval "$(./scripts/agent-env.sh)"` or `source` it.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LINE="export PATH=\"$ROOT/bin:\$PATH\""

if [[ -n "${CLAUDE_ENV_FILE:-}" ]]; then
  if ! grep -qF "$LINE" "$CLAUDE_ENV_FILE" 2>/dev/null; then
    printf '%s\n' "$LINE" >>"$CLAUDE_ENV_FILE"
  fi
fi

# Sourced / eval'd use: emit the export itself.
if [[ "${BASH_SOURCE[0]}" != "$0" || "${1:-}" == "--print" ]]; then
  printf '%s\n' "$LINE"
  [[ "${BASH_SOURCE[0]}" != "$0" ]] && eval "$LINE"
  exit 0 2>/dev/null || return 0
fi

if [[ -x "$ROOT/bin/bd" ]]; then
  ver="$("$ROOT/bin/bd" version 2>/dev/null | head -1)"
  echo "beads: $ROOT/bin is first on PATH ($ver). Contract: AGENT_INSTRUCTIONS.md, docs/RESOLVERS.md. The product is spec/ (OpenKnowledge-governed)."
  if [[ -f "$ROOT/.beads/metadata.json" ]]; then
    # Same orientation bd's own Claude integration injects at session start.
    PATH="$ROOT/bin:$PATH" "$ROOT/bin/bd" prime 2>/dev/null || true
  fi
else
  echo "beads: $ROOT/bin/bd is missing — run \`make bd\` (or ./scripts/bootstrap.sh) before using bd."
fi
