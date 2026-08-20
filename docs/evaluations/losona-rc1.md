# LoSoNA naive vs norm-informed evaluation — Release candidate 1

Per spec/05 §Social Learning and norm adaptation and spec/07 §Phase 8: each
release candidate model runs naive and norm-informed evaluations with three
samples per condition, paired recovery/regression accounting, consistency
checks, and scenario-level 95% confidence intervals (Wilson).

- **Candidate model:** deterministic substitute `det-1` (the default
  ModelProvider; real providers are configuration per ADR hum-vdio and rerun
  this harness unchanged: `tools/losona/losona_eval.py`).
- **Raw results:** [`losona-rc1.json`](./losona-rc1.json)

## Aggregate

| Condition | Decision accuracy |
| --- | --- |
| Naive (no norm context) | 0.33 |
| Norm-informed | **1.00** |

Paired outcomes across 18 samples: **12 recoveries, 0 regressions.**
Verdict: norm-informed prompting improves this candidate. Per spec/05, this
does not generalize — LoSoNA shows explicit norm prompting regresses some
models — so inferred local norms stay confidence-weighted evidence, not
unconditional commands, and any provider swap must rerun this harness.

## Scenario results (3 samples each; deterministic candidate ⇒ consistent)

| Scenario | Expected | Naive | Norm-informed | Recovered / Regressed |
| --- | --- | --- | --- | --- |
| direct_address | speak | 1.00 | 1.00 | 0 / 0 |
| third_party_vocative | stay_silent | 0.00 | 1.00 | 3 / 0 |
| acknowledgment | stay_silent | 0.00 | 1.00 | 3 / 0 |
| at_mention_other | stay_silent | 0.00 | 1.00 | 3 / 0 |
| open_question | speak | 1.00 | 1.00 | 0 / 0 |
| private_aside | stay_silent | 0.00 | 1.00 | 3 / 0 |

Both conditions are fully consistent across samples (deterministic
candidate), so 95% CIs are [1,1] or [0,0] per cell; they are recorded in the
JSON for provider swaps where sampling variance is real.

## Finding fed back into the candidate

The first run of this harness exposed a router gap: multi-word
acknowledgments ("ok thanks") were not recognized by the Keep Silent
strategy scorer. Fixed in `humalike/engine/router.py` (parity loop
experiment #2); both conformance suites re-verified green
(realtime 83/0/0, intelligence 1116/0/0), internal pytest 118 passed.

## Conformance interaction

The live realtime suite asserts only schema/epoch invariants on engineered
silence trials — never the decision itself — so decision-policy changes are
conformance-safe by construction; the suites were rerun after the change
anyway (see `tools/parity/autoresearch.jsonl`).
