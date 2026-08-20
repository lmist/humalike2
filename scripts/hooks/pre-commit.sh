#!/usr/bin/env bash
# Fail a commit that changes tracked work without a claimed bead.
# Bypass: HUM_SKIP_CLAIM=1 (docs-only / bootstrap exceptions) or BD_ISSUE=<id>.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$ROOT"
export PATH="$ROOT/bin:$PATH"

if [[ "${HUM_SKIP_CLAIM:-}" == "1" ]]; then
  exit 0
fi

if [[ ! -x bin/bd || ! -f .beads/metadata.json ]]; then
  echo "human: bd is not ready in this checkout. Run ./scripts/bootstrap.sh" >&2
  exit 1
fi

# Staged paths excluding noise
staged="$(git diff --cached --name-only --diff-filter=ACMRD || true)"
if [[ -z "$staged" ]]; then
  exit 0
fi

# Pure beads-db / ignore / knowledge-base churn can land without a claim.
# (spec/, research/, sources/ are governed by OpenKnowledge, not beads.)
if ! printf '%s\n' "$staged" | grep -vqE '^(\.beads/|\.gitignore$|\.okignore$|spec/|research/|sources/)'; then
  exit 0
fi

if [[ -n "${BD_ISSUE:-}" ]]; then
  exit 0
fi

claimed="$(bin/bd list --status in_progress --json 2>/dev/null || echo '[]')"
if printf '%s' "$claimed" | grep -q '"id"'; then
  exit 0
fi

echo "human: commit has work files but no in_progress bead." >&2
echo "  Claim first:  export PATH=\"$ROOT/bin:\$PATH\" && bd ready && bd update <id> --claim" >&2
echo "  Or set:       BD_ISSUE=<id>   or   HUM_SKIP_CLAIM=1" >&2
echo "  See:          docs/RESOLVERS.md" >&2
exit 1
