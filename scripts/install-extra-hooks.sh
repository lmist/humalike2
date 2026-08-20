#!/usr/bin/env bash
# Inject HUM sections around the managed beads hook shims.
# Content outside BEGIN/END BEADS markers survives `bd hooks install`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS="$(git -C "$ROOT" config --get core.hooksPath || true)"
if [[ -z "$HOOKS" ]]; then
  HOOKS="$ROOT/.beads/hooks"
fi
case "$HOOKS" in
  /*) ;;
  *) HOOKS="$ROOT/$HOOKS" ;;
esac
if [[ ! -d "$HOOKS" ]]; then
  echo "install-extra-hooks: no hooks dir at $HOOKS" >&2
  exit 1
fi

PATH_BLOCK_BEGIN='# --- BEGIN HUM PATH ---'
PATH_BLOCK_END='# --- END HUM PATH ---'
CHECK_BLOCK_BEGIN='# --- BEGIN HUM CHECKS ---'
CHECK_BLOCK_END='# --- END HUM CHECKS ---'

path_block() {
  cat <<'BLOCK'
# --- BEGIN HUM PATH ---
# Prefer the repo-local binary so hooks never pick Homebrew/PATH bd.
_hum_root=$(git rev-parse --show-toplevel 2>/dev/null) || _hum_root=
if [ -n "$_hum_root" ] && [ -x "$_hum_root/bin/bd" ]; then
  PATH="$_hum_root/bin:$PATH"
  export PATH
fi
# --- END HUM PATH ---
BLOCK
}

check_block() {
  local hook="$1"
  cat <<BLOCK
# --- BEGIN HUM CHECKS ---
_hum_root=\$(git rev-parse --show-toplevel 2>/dev/null) || _hum_root=
if [ -n "\$_hum_root" ] && [ -x "\$_hum_root/scripts/hooks/${hook}.sh" ]; then
  "\$_hum_root/scripts/hooks/${hook}.sh" "\$@" || exit \$?
fi
# --- END HUM CHECKS ---
BLOCK
}

strip_block() {
  local begin="$1" end="$2"
  awk -v b="$begin" -v e="$end" '
    $0 == b {skip=1; next}
    $0 == e {skip=0; next}
    !skip {print}
  '
}

patched=0
for hook in pre-commit post-merge pre-push post-checkout prepare-commit-msg; do
  f="$HOOKS/$hook"
  [[ -f "$f" ]] || continue
  tmp="$(mktemp)"
  body="$(strip_block "$PATH_BLOCK_BEGIN" "$PATH_BLOCK_END" <"$f" | strip_block "$CHECK_BLOCK_BEGIN" "$CHECK_BLOCK_END")"
  {
    echo '#!/usr/bin/env sh'
    path_block
    printf '%s\n' "$body" | awk 'NR==1 && /^#!/ {next} {print}'
    check_block "$hook"
  } >"$tmp"
  chmod +x "$tmp"
  mv "$tmp" "$f"
  chmod +x "$f"
  patched=$((patched + 1))
done

echo "install-extra-hooks: patched $patched hooks in $HOOKS"
