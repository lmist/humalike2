#!/usr/bin/env bash
# Prove every formula in .beads/formulas parses and is visible to bd.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$ROOT/bin:$PATH"
if [[ ! -x bin/bd ]]; then
  echo "check-formulas: bin/bd missing" >&2
  exit 1
fi

shopt -s nullglob
files=(.beads/formulas/*.formula.toml)
if [[ ${#files[@]} -eq 0 ]]; then
  echo "check-formulas: no formulas" >&2
  exit 1
fi

fail=0
for f in "${files[@]}"; do
  name="$(awk -F\" '/^formula = /{print $2; exit}' "$f")"
  if [[ -z "$name" ]]; then
    echo "FAIL $f — no formula = \"name\"" >&2
    fail=1
    continue
  fi
  if ! json="$(bin/bd formula show "$name" --json 2>/dev/null)"; then
    echo "FAIL $name ($f) — formula show failed" >&2
    fail=1
    continue
  fi
  steps="$(printf '%s' "$json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d.get("steps") or []))' 2>/dev/null || echo 0)"
  if [[ "$steps" == "0" ]]; then
    echo "FAIL $name ($f) — zero steps parsed" >&2
    fail=1
    continue
  fi
  echo "ok  $name  steps=$steps  $f"
done

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "check-formulas: ${#files[@]} formulas ok"
