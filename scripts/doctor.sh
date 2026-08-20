#!/usr/bin/env bash
# Repo doctor. `bd doctor` is not available in embedded-Dolt mode, so this
# checks the things docs/RESOLVERS.md section 0 cares about. Exit 1 on any FAIL.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$ROOT/bin:$PATH"
PIN="$(awk -F' *:= *' '/^VENDOR_REF/{print $2}' Makefile)"
fail=0
ok()   { printf 'ok    %s\n' "$*"; }
bad()  { printf 'FAIL  %s\n' "$*" >&2; fail=1; }
warn() { printf 'warn  %s\n' "$*" >&2; }

[[ -f vendor/beads/cmd/bd/main.go ]] && ok "vendor/beads subtree present" || bad "vendor/beads missing — ./scripts/bootstrap.sh"
if [[ -x bin/bd ]]; then
  v="$(bin/bd version 2>/dev/null | awk '{print $3}')"
  [[ "v$v" == "$PIN" ]] && ok "bin/bd is $PIN" || bad "bin/bd is v$v, Makefile pins $PIN — make bd"
else
  bad "bin/bd missing — make bd"
fi
[[ "$(command -v bd)" == "$ROOT/bin/bd" ]] && ok "PATH bd is $ROOT/bin/bd" || bad "PATH bd is $(command -v bd || echo none)"
[[ -f .beads/metadata.json ]] && ok ".beads initialized" || bad ".beads/metadata.json missing — bd init (see RESOLVERS §0)"
bin/bd info >/dev/null 2>&1 && ok "bd info answers" || bad "bd info fails — bd bootstrap --yes"
types="$(bin/bd types 2>/dev/null)"
for t in conformance question; do
  grep -q "^  $t" <<<"$types" && ok "custom type $t" || bad "custom type $t missing — make types"
done
hp="$(git config --get core.hooksPath || true)"
[[ -n "$hp" ]] && ok "core.hooksPath=$hp" || bad "core.hooksPath unset — make hooks"
for h in pre-commit prepare-commit-msg post-checkout post-merge pre-push; do
  f=".beads/hooks/$h"
  if [[ -x "$f" ]] && grep -q 'BEGIN HUM PATH' "$f" && grep -q 'BEGIN HUM CHECKS' "$f" && grep -q 'BEGIN BEADS INTEGRATION' "$f"; then
    ok "hook $h has BEADS + HUM blocks"
  else
    bad "hook $h lacks markers — make hooks"
  fi
done
for f in .claude/settings.json .codex/hooks.json .cursor/hooks.json .cursor/rules/beads.mdc scripts/agent-env.sh scripts/agent-path-rewrite.sh; do
  [[ -s "$f" ]] && ok "host hook $f" || bad "host hook $f missing"
done
python3 -c 'import json,sys; [json.load(open(p)) for p in sys.argv[1:]]' .claude/settings.json .codex/hooks.json .cursor/hooks.json 2>/dev/null && ok "host hook JSON parses" || bad "host hook JSON invalid"
for f in AGENTS.md CLAUDE.md AGENT_INSTRUCTIONS.md docs/RESOLVERS.md; do
  [[ -s "$f" ]] && ok "contract $f" || bad "contract $f missing"
done
git ls-files --error-unmatch bin/bd >/dev/null 2>&1 && bad "bin/bd is tracked — git rm --cached bin/bd" || ok "bin/bd not tracked"
git ls-files --error-unmatch .env >/dev/null 2>&1 && bad ".env is tracked — secrets must stay untracked" || ok ".env not tracked"
if ./scripts/check-formulas.sh >/tmp/hum-doctor-formulas.$$ 2>&1; then ok "$(tail -1 /tmp/hum-doctor-formulas.$$)"; else cat /tmp/hum-doctor-formulas.$$ >&2; bad "formulas"; fi
rm -f /tmp/hum-doctor-formulas.$$
n="$(bin/bd list --status open --label bootstrap --json 2>/dev/null | grep -c '"id"' || true)"
[[ "$n" -gt 0 ]] && warn "$n open bootstrap beads — finish or close them with evidence" || ok "no open bootstrap beads"
[[ $fail -eq 0 ]] && echo "doctor: healthy" || { echo "doctor: problems found" >&2; exit 1; }
