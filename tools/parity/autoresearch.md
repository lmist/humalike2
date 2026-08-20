# Autoresearch: Humalike API parity

## Objective

Discover and hold live-contract parity between the recreation (`service/`)
and the tested Humalike API. The workload is both committed conformance
suites run end-to-end against a freshly booted recreation with deterministic
model substitutes. This loop is the phase-8 parity gate (bead hum-4ko6):
any change to the service is an experiment; the suites are the judge.

## Metrics

- **Primary**: `total_failed` (count, lower is better; target and current
  baseline: 0) — failed assertions across both suites.
- **Secondary**: `total_passed` (higher), `total_skipped` (must stay 0 for a
  release candidate), per-suite splits (`realtime_*`, `intelligence_*`).

## How to Run

`bash tools/parity/autoresearch.sh` — boots a fresh server on
`PARITY_PORT` (default 8290) with a scratch database, mints a key, runs
`tests/realtime` then `tests/intelligence`, and prints `METRIC name=value`
lines. Takes about 60 seconds.

Checks: `bash tools/parity/autoresearch.checks.sh` runs the internal pytest
suite (must stay green for any keep).

## Files in Scope

Anything under `service/humalike/` (routes, engines, middleware, billing,
scheduler, storage). One hypothesis per experiment.

## Off Limits

`tests/realtime/`, `tests/intelligence/` (the oracle is never edited to
pass), `spec/`, `research/`, `sources/` (OpenKnowledge-governed), `.beads/`.

## Constraints

- Internal pytest suite must pass for any keep.
- Zero skips: a skip means credit depletion or suppressed billable blocks —
  investigate, never accept.
- Exit code 3 from a suite is a budget blocker, never a regression.
- No new runtime dependencies without an ADR.

## Termination

Run until interrupted. The gate condition for Release candidate 1 is
`total_failed == 0` and `total_skipped == 0` on the candidate commit,
recorded in `autoresearch.jsonl`.

## What's Been Tried

- Baseline (RC1 candidate, commit 7ccd1a9 lineage): **total_failed=0**
  (realtime 83/0/0, intelligence 1116/0/0). Parity discovered through
  suite-first development: every engine was written against the pinned
  assertions, with deterministic substitutes satisfying the semantic gates
  (seeded recall/ask attribution, 2-5 bubble naturalization,
  merge-not-truncate, population validation passed:true, subject-scoped
  foresee).
- Dead end to avoid: stock FastAPI validation serializer (emits a leading
  "body" loc segment and fails the 422 contract) — the custom handler in
  `humalike/errors.py` strips it.
- Dead end to avoid: sharing one HMAC secret between server and key-mint
  shell sessions implicitly; always pass `HUMALIKE_SECRET` explicitly.
- SQLite returns naive datetimes; scheduler recovery must normalize to
  UTC-aware before pacing arithmetic (fixed; covered by test_hardening).
