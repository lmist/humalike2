#!/usr/bin/env bash
# Prefix the commit subject with a bead id: BD_ISSUE if set, else the single
# in_progress bead when exactly one is claimed. Leaves the subject alone if it
# already starts with a hum-N id.
set -euo pipefail
msg_file="${1:-}"
[[ -n "$msg_file" && -f "$msg_file" ]] || exit 0

# Skip merge/squash/amend generated messages
kind="${2:-}"
case "$kind" in
  merge|squash|commit) exit 0 ;;
esac

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
export PATH="$ROOT/bin:$PATH"

subject="$(head -n1 "$msg_file")"
case "$subject" in
  hum-[0-9]*) exit 0 ;;
  "") exit 0 ;;
esac

id="${BD_ISSUE:-}"
if [[ -z "$id" && -x "$ROOT/bin/bd" && -f "$ROOT/.beads/metadata.json" ]]; then
  ids="$("$ROOT/bin/bd" list --status in_progress --json 2>/dev/null \
    | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    d=[]
items=d if isinstance(d,list) else (d.get("issues") or [])
print("\n".join(i.get("id","") for i in items if i.get("id")))' 2>/dev/null || true)"
  if [[ "$(printf '%s\n' "$ids" | grep -c . || true)" == "1" ]]; then
    id="$ids"
  fi
fi
[[ -n "$id" ]] || exit 0

tmp="$(mktemp)"
{ printf '%s: %s\n' "$id" "$subject"; tail -n +2 "$msg_file"; } >"$tmp"
mv "$tmp" "$msg_file"
