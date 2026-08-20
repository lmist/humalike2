#!/bin/bash
# API parity benchmark for the autoresearch loop (bead hum-4ko6).
# Boots a fresh recreation, runs BOTH live conformance suites against it, and
# emits structured METRIC lines. Primary metric: total_failed (lower is
# better, target 0). Secondary: total_passed, total_skipped, per-suite splits.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${HUMALIKE_PY:-$ROOT/.venv/bin/python}"
PORT="${PARITY_PORT:-8290}"
DB="$(mktemp -u /tmp/parity-XXXXXX).db"
LOG="$(mktemp /tmp/parity-server-XXXXXX.log)"

# Pre-check: the service must import cleanly (<1s) before paying for a run.
(cd "$ROOT/service" && "$PY" -c "import humalike.app") || { echo "SYNTAX ERROR"; exit 1; }

env -i HOME="$HOME" PATH="$ROOT/.venv/bin:/usr/bin:/bin" \
  HUMALIKE_PORT="$PORT" HUMALIKE_SECRET=parity-secret \
  HUMALIKE_DATABASE_URL="sqlite:///$DB" \
  "$PY" -m humalike.main >"$LOG" 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true; rm -f "$DB"*' EXIT
sleep 2

KEY=$(cd "$ROOT/service" && HUMALIKE_SECRET=parity-secret HUMALIKE_DATABASE_URL="sqlite:///$DB" \
  "$PY" -c "from humalike.db import create_all; from humalike.auth import mint_key; create_all(); print(mint_key())")

export HUMALIKE_API_KEY="$KEY" HUMALIKE_API_URL="http://127.0.0.1:$PORT" HUMALIKE_POLL_MS=200

RT_OUT=$("$ROOT/tests/realtime/run.sh" 2>&1 || true)
RT_SUMMARY=$(echo "$RT_OUT" | grep '^SUMMARY' | tail -1)
RT_PASS=$(echo "$RT_SUMMARY" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+')
RT_FAIL=$(echo "$RT_SUMMARY" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+')
RT_SKIP=$(echo "$RT_SUMMARY" | grep -oE '[0-9]+ skipped' | grep -oE '[0-9]+')

IN_OUT=$(node "$ROOT/tests/intelligence/run.mjs" 2>&1 || true)
IN_SUMMARY=$(echo "$IN_OUT" | grep '^SUMMARY' | tail -1)
IN_PASS=$(echo "$IN_SUMMARY" | grep -oE 'pass=[0-9]+' | grep -oE '[0-9]+')
IN_FAIL=$(echo "$IN_SUMMARY" | grep -oE 'fail=[0-9]+' | grep -oE '[0-9]+')
IN_SKIP=$(echo "$IN_SUMMARY" | grep -oE 'skip=[0-9]+' | grep -oE '[0-9]+')

echo "METRIC realtime_passed=${RT_PASS:-0}"
echo "METRIC realtime_failed=${RT_FAIL:-999}"
echo "METRIC realtime_skipped=${RT_SKIP:-0}"
echo "METRIC intelligence_passed=${IN_PASS:-0}"
echo "METRIC intelligence_failed=${IN_FAIL:-999}"
echo "METRIC intelligence_skipped=${IN_SKIP:-0}"
echo "METRIC total_failed=$(( ${RT_FAIL:-999} + ${IN_FAIL:-999} ))"
echo "METRIC total_passed=$(( ${RT_PASS:-0} + ${IN_PASS:-0} ))"
echo "METRIC total_skipped=$(( ${RT_SKIP:-0} + ${IN_SKIP:-0} ))"
