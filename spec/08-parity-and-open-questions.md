---
title: Live Conformance and Open Questions
description: Production parity strategy based on roughly 1,360 live assertions and explicit unresolved behavior.
tags:
  - humalike
  - specification
  - testing
  - open-questions
status: complete
---
# Live conformance and open questions

## Normative parity mechanism

The committed suites are the transport and behavior oracle:

- `tests/realtime/run.sh` runs `tests/realtime/run.mjs` plus the WSS driver and completes **83 live assertions** covering identity, usage, authentication on every route, validation types, unknown-field tolerance, accept-side limits, threads, grants, epochs, decisions, events, pacing (floor, defaults, formula), WSS frame sequence and ids, dual sockets, garbage and expired grants, Social Signals negative behavior, Social Memory, owner-wide idempotency, and billing deltas. [Realtime evidence](../research/tested-realtime-memory.md)
- `tests/intelligence/run.sh` runs `tests/intelligence/run.mjs` and completes **about 1,280–1,360 live assertions** (the count moves with poll counts and generated field counts; the latest confirming run passed 1,278 with 0 failures and 0 skips) covering Social Learning, foresee, analyze/report absence, audit grammar, limits, progression and index semantics, persona generation/enhancement/validation down to gate names and detail strings, every endpoint-specific error literal, timings, and free terminal polling. [Intelligence evidence](../research/tested-intelligence-personas.md)

Together these roughly **1,360 live assertions** are the normative parity gate. They make real calls with fresh identifiers, pin every learnable literal in code, and MUST remain independent of recorded production responses. Cite the assertion set, not a fixed count. [Realtime runner](../tests/realtime/run.mjs) [Intelligence runner](../tests/intelligence/run.mjs)

## Running the suites

Use Node 24 (any Node with global `fetch` works) and a funded test key. Both scripts read `HUMALIKE_API_KEY` from the environment or the project `.env` (guarded; `.env` MUST never be tracked), `HUMALIKE_API_URL` to target a recreation instead of production (WSS protocol and host expectations derive from it), and `NODE` to override the interpreter. TCP connect timeouts (the request was never sent) are retried up to three times with backoff; any other transport error aborts the run loudly. Exit codes are 0 green, 1 assertion failures or abort, and **3 credit-depleted**: a 402 records per-block `SKIP` entries and MUST be reported as an environment/budget blocker, never reinterpreted as a product regression. [Realtime runner](../tests/realtime/run.sh) [Intelligence runner](../tests/intelligence/run.sh)

```sh
export HUMALIKE_API_KEY=ak_...          # or keep it in ./.env
export HUMALIKE_API_URL=http://localhost:8080   # omit for production
./tests/realtime/run.sh
./tests/intelligence/run.sh
```

Run sequentially when measuring component credit deltas; concurrent runs mix account-wide usage buckets (the suites scope their billing assertions to `turn-taking`/`theoryofmind` and `personas`/`social-observability` respectively, but `theoryofmind` is shared). The intelligence run takes 8–12 minutes because population and enhancement are asynchronous. A recreation MUST implement `usage-summary` with the production component slugs before either suite can complete. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

## Assertion policy

Exact assertions cover method/path, status, content type, `x-request-id`, rate-header absence, field keys, enum values, literal status strings, nullability, error casing, messages, and details, `loc` prefixing, owner-safe absence, idempotency, epoch progression, schedule positions/times/status, pacing constants, WSS order/ids/metadata, grant shape and TTL, job transitions and phase vocabularies, gate names and detail strings, normalization defaults, numeric ranges, and billing invariants. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

Generated prose is tested by type and semantic invariants: required facts are present, ignored facts are absent, seed markers survive, ordering is preserved, evidence ids originate in input, and enum/range constraints hold. Tests MUST NOT require exact paraphrases. A nondeterministic decision such as `stay_silent` is asserted exactly whenever it occurs without requiring the model to choose it on every run. Model-dependent gates that a recreation's deterministic substitutes MUST still satisfy: recall/ask surface seeded tokens with correct attribution and order, a multi-paragraph draft under a "send separately" prompt yields 2–5 bubbles, a six-paragraph draft merges to at most five without losing content, a generated population validates with `passed:true`, and foresee models exactly the named subject. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

Two assertions encode production as the target on purpose: enhanced personas MUST return `fields:{}`, and `analyze` MUST NOT expose a report id. A recreation that "improves" either diverges from the 1:1 contract and fails the gate. [Intelligence evidence](../research/tested-intelligence-personas.md)

New production discoveries MUST first become fresh live assertions, then update the tested research digest, and only then change normative prose. Documentation-only fields remain non-normative where live behavior contradicts them; documented-but-untested shapes (the 402/403/502 bodies, the failed-job `error` category) are carried in the spec as explicit documented defaults. [Specification index](./00-index.md)

## Credit awareness

A realtime run costs about 32 calls and 52 credits (`turn-taking` 13/15, `theoryofmind` 6/24, `social-memory` 13/13). An intelligence run costs about 800–880 credits (`personas` ≈580–640 over 7 calls, `social-observability` ≈150–165 over 13–15 calls, `social-learning` ≈30 over 2, `theoryofmind` ≈30–40 over 8–10); terminal re-polling of all completed resources adds exactly zero calls and credits. These are planning observations, not guaranteed prices. Use dedicated keys or sequential runs for clean attribution and set an explicit verification budget. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

## Release gates

A release candidate MUST:

- pass both suites with zero failed assertions and zero skips against `HUMALIKE_API_URL` pointing at the candidate, except that a clearly identified exit code 3 blocks billable verification rather than changing the contract;
- preserve first-write idempotency and stale-epoch atomicity under local concurrency tests;
- prevent cross-tenant reads in local security tests;
- emit no bearer key, WSS grant, or account identity in logs or tracked files;
- keep public docs and generated client types synchronized with this specification; and
- record which production open questions remain unsupported.

The cross-tenant, concurrency, and secret-handling gates are internal engineering tests because a single production key cannot safely establish them. [Protocol](./02-protocol-auth-errors.md)

## Corrected contradictions

The live contract supersedes these earlier assumptions: `attached` is a distinct `{type,channel,server_time}` frame; late expired and garbage grants close with code 4000 after upgrade; delivered WSS message ids differ from HTTP schedule ids; changed-body and changed-scope idempotency replay returns the first 200 result under an `(owner,key)` index; same-body replay does not duplicate memory; typing time has a 500 ms floor and the 200 ms bubble gap sits outside `max_typing_ms`; default pacing is 0/150/8000; unknown request fields are ignored; timestamps are microsecond `Z` strings; metadata echoes on every zero-based bubble and is `null` when omitted; Social Signals produced neither frames nor tags under documented triggers; analyze exposes no report identifier; the audit enforces a ~32,768-token budget beside the 250-message cap; audit indexes are 0-based transcript positions; enhanced personas have empty fields and identical prompt/markdown; blueprints include their full extended schema, explicit nulls, and conditional-only distributions; validation fills documented defaults and uses `schema`/`constraints` scorecard gates plus `max_pairwise_similarity`/`marginal_tvd:*` batch gates; audit progress uses nullable sections with `replies:[]` from the start; and error shape varies by endpoint with exact literals. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

## Honest open questions

1. **Analyze report linkage:** the action exposes no report id or location, so read-back of that exact report is unreachable through the tested public flow. [Intelligence evidence](../research/tested-intelligence-personas.md)
2. **Social Signals trigger:** all documented trigger combinations produced empty tags and no signal event; another undocumented trigger may exist, but no signal payload is normative. [Realtime evidence](../research/tested-realtime-memory.md)
3. **Tenant boundaries:** nonexistent repository ids return `null`, but other-owner behavior cannot be tested with one key. [Intelligence evidence](../research/tested-intelligence-personas.md)
4. **Credit exhaustion:** the 402 body is documented but was not exercised; reservation release, replenishment timing, and recovery after funding are unobserved. [Protocol](./02-protocol-auth-errors.md)
5. **Authorization and throttling:** exact 403 and 429 bodies, quotas, and rate headers are untested; no rate headers appeared in any sampled response. [Realtime evidence](../research/tested-realtime-memory.md)
6. **Thread edge cases:** create-with-supplied-UUID and reopen are proven; cross-owner UUID behavior is not. [Realtime evidence](../research/tested-realtime-memory.md)
7. **Grant boundary:** code 4000 is proven about two seconds after expiry and for garbage tokens, not for every late-connect interval; token payload contents are opaque. [Realtime evidence](../research/tested-realtime-memory.md)
8. **Model policy:** decision prompts/models, split heuristics within the 1–5 bound, strategy tie-breaking, and the model-authored `meta.channels` for channel-less transcripts are not deterministic contracts. [HUMA digest](../research/paper-huma.md) [Intelligence evidence](../research/tested-intelligence-personas.md)
9. **Failure payloads:** no persona job or audit reached `status:"failed"`, so the non-null `error` payload is documented only (`"provider_error"`); the stored Report read shape is likewise unobserved. [Intelligence evidence](../research/tested-intelligence-personas.md)
10. **Operational policy:** retention, deletion, residency, production encryption details, provider/model versions, prompt versions, and device-authorization support are not public behavioral contracts. [Plugin analysis](../research/plugin-analysis.md) [HUMA digest](../research/paper-huma.md)

Unknowns MUST remain configuration, local safety requirements, documented defaults, or explicitly unsupported behavior. They MUST NOT be represented as established production behavior.