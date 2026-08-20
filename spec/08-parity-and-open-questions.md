---
title: Live Conformance and Open Questions
description: Production parity strategy based on 652 live assertions and explicit unresolved behavior.
tags: [humalike, specification, testing, open-questions]
status: complete
---
# Live conformance and open questions

## Normative parity mechanism

The committed suites are the transport and behavior oracle:

- `tests/realtime/run.sh` runs `tests/realtime/run.mjs` plus the WSS driver and contains **60 passing live assertions** covering identity, usage, authentication, validation, threads, epochs, decisions, events, pacing, WSS, Social Signals negative behavior, Social Memory, idempotency, and billing deltas. [Realtime evidence](../research/tested-realtime-memory.md)
- `tests/intelligence/run.sh` runs `tests/intelligence/run.mjs` and contains **592 passing live assertions** covering Social Learning, foresee, analyze/report absence, audit, persona generation/enhancement/validation, endpoint-specific errors, timings, and free terminal polling. [Intelligence evidence](../research/tested-intelligence-personas.md)

Together, the **652 live assertions** are the normative parity gate. They make real calls with fresh identifiers and MUST remain independent of recorded production responses. [Realtime runner](../tests/realtime/run.mjs) [Intelligence runner](../tests/intelligence/run.mjs)

## Running the suites

Use Node 24 and a funded test key. The scripts load `HUMALIKE_API_KEY` from the environment or project `.env`; `.env` MUST never be tracked. [Realtime runner](../tests/realtime/run.sh) [Intelligence runner](../tests/intelligence/run.sh)

```sh
set -a
source /Users/lou/human/.env
set +a
./tests/realtime/run.sh
./tests/intelligence/run.sh
```

Run sequentially when measuring component credit deltas; concurrent runs mix account-wide usage buckets. The intelligence run can take several minutes because population and enhancement are asynchronous. A 402 MUST stop further discretionary billable verification, be reported as an environment/budget blocker, and MUST NOT be reinterpreted as a product regression. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

## Assertion policy

Exact assertions MUST cover method/path, status, content type, `x-request-id`, field keys, enum values, nullability, error casing/details, owner-safe absence, idempotency, epoch progression, schedule positions/times, WSS order/ids/metadata, job transitions, and billing invariants. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

Generated prose MUST be tested by type and semantic invariants: required facts are present, ignored facts are absent, seed markers survive, ordering is preserved, evidence ids originate in input, and enum/range constraints hold. Tests MUST NOT require exact paraphrases. A nondeterministic decision such as `stay_silent` may be captured as proven behavior without requiring the model to choose it on every future run; the response schema remains exact whenever it occurs. [Realtime evidence](../research/tested-realtime-memory.md)

New production discoveries MUST first become fresh live assertions, then update the tested research digest, and only then change normative prose. Documentation-only fields remain non-normative where live behavior contradicts them. [Specification index](./00-index.md)

## Credit awareness

The expanded realtime reference run attributed 25 calls and 32 credits to its own components after excluding a concurrent persona run. The intelligence reference run observed substantial persona cost and an account-wide 759-credit delta with sibling activity; terminal re-polling itself added exactly zero calls and credits. These values are planning observations, not guaranteed prices. Use dedicated keys or sequential runs for clean attribution and set an explicit verification budget. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

## Release gates

A release candidate MUST:

- pass both suites with zero failed assertions, except that a clearly identified 402 blocks billable verification rather than changing the contract;
- preserve first-write idempotency and stale-epoch atomicity under local concurrency tests;
- prevent cross-tenant reads in local security tests;
- emit no bearer key, WSS grant, or account identity in logs or tracked files;
- keep public docs and generated client types synchronized with this specification; and
- record which production open questions remain unsupported.

The cross-tenant, concurrency, and secret-handling gates are internal engineering tests because a single production key cannot safely establish them. [Protocol](./02-protocol-auth-errors.md)

## Corrected contradictions

The live contract supersedes these earlier assumptions: `attached` is a distinct `{type,channel,server_time}` frame; late expired grants close with code 4000 after upgrade; delivered WSS message ids differ from HTTP schedule ids; changed-body idempotency replay returns the first 200 result and preserves only the first body; same-body replay does not duplicate memory; the 200 ms bubble gap sits outside `max_typing_ms`; metadata echoes on every zero-based bubble; Social Signals produced neither frames nor tags under documented triggers; analyze exposes no report identifier; enhanced personas can have empty fields; blueprints include their full extended schema and explicit nulls; constraints use an aggregate gate; audit progress uses nullable sections; and error shape varies by endpoint. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

## Honest open questions

1. **Analyze report linkage:** the action exposes no report id or location, so read-back of that exact report is unreachable through the tested public flow. [Intelligence evidence](../research/tested-intelligence-personas.md)
2. **Social Signals trigger:** all documented trigger combinations produced empty tags and no signal event; another undocumented trigger may exist, but no signal payload is normative. [Realtime evidence](../research/tested-realtime-memory.md)
3. **Tenant boundaries:** nonexistent repository ids return `null`, but other-owner behavior cannot be tested with one key. [Intelligence evidence](../research/tested-intelligence-personas.md)
4. **Credit exhaustion:** exact 402 body, reservation release, replenishment timing, and recovery after funding were not exercised in the final runs. [Intelligence evidence](../research/tested-intelligence-personas.md)
5. **Authorization and throttling:** exact 403, 429, quotas, and successful rate headers are untested; no rate headers appeared in sampled traffic. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)
6. **Thread edge cases:** reopening an existing UUID is proven; behavior for a caller-supplied nonexistent UUID and cross-owner UUID is not. [Realtime evidence](../research/tested-realtime-memory.md)
7. **Grant boundary:** code 4000 is proven around 1.5 seconds after expiry, not for every possible late-connect interval. [Realtime evidence](../research/tested-realtime-memory.md)
8. **Strictness and defaults:** unknown request fields, default pacing, minimum typing delay, split policy, decision prompts/models, and strategy tie-breaking remain unknown. [Realtime evidence](../research/tested-realtime-memory.md) [HUMA digest](../research/paper-huma.md)
9. **Repository linkage and failures:** stored Report success shape through a reachable id, other-owner absence, and terminal failed persona resource payloads remain unobserved. [Intelligence evidence](../research/tested-intelligence-personas.md)
10. **Operational policy:** retention, deletion, residency, production encryption details, provider/model versions, prompt versions, and device-authorization support are not public behavioral contracts. [Plugin analysis](../research/plugin-analysis.md) [HUMA digest](../research/paper-huma.md)

Unknowns MUST remain configuration, local safety requirements, or explicitly unsupported behavior. They MUST NOT be represented as established production behavior.