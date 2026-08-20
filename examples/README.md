# Examples

Small runnable scripts, one per context, written against the typed clients in
`clients/`. Every script reads the same two variables the conformance suites
read:

```sh
export HUMALIKE_API_URL=http://127.0.0.1:8191   # omit for production
export HUMALIKE_API_KEY=ak_...
node examples/01-whoami-usage.mjs
python3 examples/04-social-memory-idempotency.py
```

The Node scripts need Node 18+ for global `fetch`; `02` uses the global
`WebSocket` from Node 22+ and falls back to the `ws` package in
`tests/realtime/node_modules` on older interpreters. The Python scripts need
only the standard library.

These are examples, not a test suite: the live suites under `tests/` are the
parity oracle. Each script does assert the invariants it demonstrates, so a
non-zero exit means the surface it exercises has drifted — but a passing run
is a smoke signal, not a conformance claim.

## Phase map

| Example | Phase (spec/07) | Language | What it demonstrates |
| --- | --- | --- | --- |
| `01-whoami-usage.mjs` | 1 — Identity, tenancy, credits | node | Bearer auth resolving to an owner, the seven-entry zero-filled `daily_series`, and the six fixed component slugs. Both routes are free. |
| `02-open-thread-and-listen-ws.mjs` | 2 — Thread state and realtime delivery | node | Grant shape (one `token`, two base64url segments, ~30 s TTL), the distinct `attached` frame, and the exact N+3 sequence with zero-based positions, echoed metadata, and delivery ids that differ from schedule ids. |
| `03-turn-taking-respond-pacing.mjs` | 3 — Model-backed turn-taking | node | Decisions and free events, the full pacing formula recomputed locally within ±10 ms (500 ms floor, 200 ms gap outside `max_typing_ms`, 0/150/8000 defaults), and a stale epoch returning exactly `{scheduled:[],superseded:true}` with no charge. |
| `04-social-memory-idempotency.py` | 4 — Social Memory | python | Ordered ingest, subject attribution surviving a different speaker, grounded `ask`, an empty scope returning `{context:""}`, and all three owner-wide `Idempotency-Key` replay classes (identical, changed body, other scope). |
| `05-social-learning-extract.py` | 5 — Social Learning | python | Echoed `meta.source`, exact `meta.message_count`, confidences in [0,1], non-empty `prompt_block` — and deliberately no assertion on the model-authored `meta.channels`. |
| `06-foresee.py` | 5 — Theory of Mind | python | `subject_name` narrowing both arrays to exactly one named entry, emotion intensities in [0,1], risk enums, and the 422 that `conversation`/`draft` produce because they are not aliases. |
| `07-analyze-report.mjs` | 6 — Observability | node | A synchronous report with **no** id, all six interaction types in `interaction_totals` and every `per_user.distribution`, counts consistent with `interactions`, evidence ids originating in the input, and `Report/by-id` returning `null` for an unknown UUID versus 400 for a malformed one. |
| `08-audit-lifecycle.mjs` | 6 — Full audit | node | Prepare/launch/poll with first-write-wins relaunch, a projection that never exposes `status` or `stage`, `replies` starting as `[]`, 0-based verdict indexes pointing at agent turns, and free terminal polling. |
| `09-personas-lifecycle.py` | 7 — Personas | python | Generation (ids `p0001`…, blueprint-aligned field maps, fixed `system_prompt` preamble, TVD arithmetic), enhancement (empty `fields`, identical prompt/markdown, verbatim seed), and validation (`schema`/`constraints` scorecard gates, batch gates, the empty no-blueprint verdict). |

Phase 0 is the live-suite harness and phase 8 is hardening; neither adds a
public surface an example could demonstrate. Their behaviors show up inside
the examples above instead — the `x-request-id` printed by `01`, the
supersession and idempotency checks in `03` and `04`, and the free-polling
checks in `08`.

## Cost

`01`-`04` are cheap: a realtime pass costs roughly 32 calls and 52 credits in
total. `09` is the expensive one (population generation dominated the live
intelligence run at roughly 580-640 credits for a full-size population), which
is why it defaults to a count of three and honours `EXAMPLE_PERSONA_COUNT`.
Against production these are real charges; against a local recreation they are
ledger rows in your own database.
