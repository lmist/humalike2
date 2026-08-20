# Dashboards

Five Grafana dashboards, one per phase group, panelled against the metric
names declared in `service/humalike/metrics.py`. spec/06 §Reliability and
scaling names the signals a deployment must track — request latency, model
stage latency, queue lag, schedule lateness, WSS connections/closes, epoch
supersessions, idempotency replays, credit reservations/captures, and
conformance suite results — and every one of them has a panel here.

| File | Dashboard uid | Phases (spec/07) |
| --- | --- | --- |
| `realtime.json` | `humalike-realtime` | 2-3 — thread state, WSS delivery, turn-taking |
| `memory.json` | `humalike-memory` | 4 — Social Memory and idempotency |
| `intelligence.json` | `humalike-intelligence` | 5-6 — learning, foresee, analyze, audit |
| `personas.json` | `humalike-personas` | 7 — asynchronous persona jobs |
| `billing.json` | `humalike-billing` | 0-1 and 8 — credits, auth outcomes, release gates |

## Wiring

The service exposes its in-process registry at:

- `GET /internal/metrics` — the whole registry as JSON, and
- `GET /internal/metrics/prometheus` — the same series in text exposition
  format, which is what these dashboards' Prometheus datasource scrapes.

Both live on `/internal`, outside `/v1`, so they are neither part of the public
contract nor behind the gateway's bearer check. Bind them to an operator
network or block them at the ingress.

Each dashboard declares a `datasource` template variable, so import with
"Import dashboard → paste JSON" and pick the Prometheus datasource; no uid is
hard-coded.

Recording is best-effort: `metrics.py` imports nothing else from the service
and every helper swallows its own failures, so a metrics problem can never
change a response body.

## Panels by phase

### Phase 0 — Live contract harness

| Panel | Dashboard | Reads |
| --- | --- | --- |
| Requests by status | `billing.json` | `humalike_requests_total` |
| Request latency p95 (all routes) | `billing.json` | `humalike_request_latency_ms` |
| Conformance assertions — realtime suite | `billing.json` | `humalike_conformance_assertions` |
| Conformance assertions — intelligence suite | `billing.json` | `humalike_conformance_assertions` |

The two conformance panels are the release gate in visual form: 83 passed / 0
failed / 0 skipped for realtime, and about 1,280-1,360 passed with no failures
or skips for intelligence. A skip normally means a 402 truncated billable
checks (suite exit code 3), which is a budget blocker rather than a product
regression.

### Phase 1 — Identity, tenancy, and credits

| Panel | Dashboard | Reads |
| --- | --- | --- |
| Reservations, captures, releases by component | `billing.json` | `humalike_credit_reservations_total`, `humalike_credit_captures_total`, `humalike_credit_releases_total` |
| Uncaptured reservation rate (leak detector) | `billing.json` | the three above |
| Credits reserved vs captured | `billing.json` | `humalike_credits_reserved_total`, `humalike_credits_captured_total` |
| Credits captured by component | `billing.json` | `humalike_credits_captured_total` |
| Credit denials (402 path) | `billing.json` | `humalike_credit_denials_total` |

The leak detector is the one to alert on: reserve-minus-capture-minus-release
should hover at zero, and a persistent positive value means reservations are
being abandoned and only the reconciler will free them.

### Phase 2 — Thread state and realtime delivery

| Panel | Dashboard | Reads |
| --- | --- | --- |
| Turn-taking request rate by route | `realtime.json` | `humalike_requests_total` |
| Turn-taking latency p95 by route | `realtime.json` | `humalike_request_latency_ms` |
| Schedule lateness | `realtime.json` | `humalike_schedule_lateness_ms` |
| WSS connections and closes | `realtime.json` | `humalike_ws_connections_active`, `humalike_ws_connections_total`, `humalike_ws_closes_total` |
| WSS frames by type | `realtime.json` | `humalike_ws_frames_total` |

Schedule lateness is the delivery contract in one line: production trailed
`deliver_at` by 6-251 ms, so a growing p95 means the N+3 sequence is drifting
away from the pacing the client was promised.

### Phase 3 — Model-backed turn-taking

| Panel | Dashboard | Reads |
| --- | --- | --- |
| Model stage latency p95 | `realtime.json` | `humalike_model_stage_latency_ms` |
| Epoch advances vs supersessions | `realtime.json` | `humalike_epoch_advances_total`, `humalike_epoch_supersessions_total` |
| Turn-taking error rate by status | `realtime.json` | `humalike_requests_total` |

### Phase 4 — Social Memory

| Panel | Dashboard | Reads |
| --- | --- | --- |
| Social Memory request rate by route | `memory.json` | `humalike_requests_total` |
| Social Memory latency p95 by route | `memory.json` | `humalike_request_latency_ms` |
| Idempotency replays by class | `memory.json` | `humalike_idempotency_replays_total` |
| Replay share of ingest | `memory.json` | `humalike_idempotency_replays_total`, `humalike_requests_total` |
| Recall outcome | `memory.json` | `humalike_memory_recall_hits_total` |
| Memory stage latency p95 | `memory.json` | `humalike_model_stage_latency_ms` |

Replays are labelled by class — `same_body`, `changed_body`, `other_scope` —
because the last two are the interesting ones: they are correct server
behavior (the first response replays and nothing is stored) but almost always
a client bug worth reporting.

### Phase 5 — Social Learning and foresee

| Panel | Dashboard | Reads |
| --- | --- | --- |
| Intelligence request rate by route | `intelligence.json` | `humalike_requests_total` |
| Intelligence latency p95 by route | `intelligence.json` | `humalike_request_latency_ms` |
| Model stage latency p95 (learning, foresee, analyze) | `intelligence.json` | `humalike_model_stage_latency_ms` |
| Model stage outcomes | `intelligence.json` | `humalike_model_stage_total` |

### Phase 6 — Observability and audit

| Panel | Dashboard | Reads |
| --- | --- | --- |
| Audit queue lag p95 | `intelligence.json` | `humalike_queue_lag_ms` |
| Audit job duration p95 by stage | `intelligence.json` | `humalike_job_duration_ms` |
| Audit job outcomes | `intelligence.json` | `humalike_jobs_total` |
| Audit projection polls | `intelligence.json` | `humalike_requests_total` |
| Intelligence error rate by status | `intelligence.json` | `humalike_requests_total` |

Audit work ran about 20 s live, so queue lag well above that is worker
starvation rather than model time. Projection polling is free, so the poll
panel is load, not revenue.

### Phase 7 — Personas

| Panel | Dashboard | Reads |
| --- | --- | --- |
| Persona action rate | `personas.json` | `humalike_requests_total` |
| Repository poll rate (free) | `personas.json` | `humalike_requests_total` |
| Job duration p95 by kind | `personas.json` | `humalike_job_duration_ms` |
| Queue lag p95 by queue | `personas.json` | `humalike_queue_lag_ms` |
| Job outcomes by kind | `personas.json` | `humalike_jobs_total` |
| Failed jobs (last 6h) | `personas.json` | `humalike_jobs_total` |

Population ran about 52 s, enhancement about 37 s, and evaluation about 3.5 s
live. Those are capacity inputs, not SLOs. The failed-jobs stat is deliberately
a single number: no persona job reached `status:"failed"` in any live run, so
any non-zero value means the deployment is exercising a path whose error
payload is documented only (`docs/unresolved-behavior.md`, phase 7).

### Phase 8 — Hardening

Phase 8 adds no surface of its own; it watches the panels above for the
properties local tests assert:

| Property | Panel |
| --- | --- |
| Reservation release on failure, 402 before billable work | Uncaptured reservation rate, Credit denials (`billing.json`) |
| Idempotency under concurrency | Idempotency replays by class (`memory.json`) |
| Stale-epoch atomicity | Epoch advances vs supersessions (`realtime.json`) |
| Crash recovery of schedules | Schedule lateness, WSS frames by type (`realtime.json`) |
| Queue duplication and provider failover | Job outcomes, Model stage outcomes (`personas.json`, `intelligence.json`) |
| Release-candidate conformance | Conformance assertion stats (`billing.json`) |

## What is deliberately absent

- **No per-owner or per-thread labels.** Owner ids, thread ids, scope ids, and
  transcript text never enter a metric label; they would turn a dashboard into
  a data-disclosure surface and blow up cardinality (spec/06 §Security).
- **No rate-limit panels.** No sampled production response exposed rate
  headers and no quota is established, so there is nothing honest to chart
  (spec/02 §Rate limiting).
- **No credit-price panel.** Component prices observed during shared runs are
  informative, not stable public pricing; the dashboards chart captured credits
  as recorded, not a modelled cost.
