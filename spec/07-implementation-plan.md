---
title: Implementation Plan
description: Phased delivery plan for a live-conformant Humalike API recreation.
tags: [humalike, specification, implementation-plan]
status: complete
---
# Implementation plan

## Phase 0 — Live contract harness

Adopt the committed realtime and intelligence suites as executable acceptance tests. Parameterize target origin so the same assertions can run against production and the recreation; preserve fresh per-run ids and semantic assertions over generated text. Implement request-id middleware and route-specific error serializers before model behavior. Exit when the recreation can run the non-model portions without altering test expectations. [Conformance strategy](./08-parity-and-open-questions.md)

## Phase 1 — Identity, tenancy, and credits

Implement bearer verification, owner injection, repository predicates, credit reservations/captures, usage projection, and `whoami`. Match the exact 401 body and 422 request-validation shape. Add internal tenant-isolation and billing-atomicity tests; live production cannot prove cross-tenant behavior with one key. [Protocol](./02-protocol-auth-errors.md)

## Phase 2 — Thread state and realtime delivery

Implement create/reopen, integration update/preserve behavior, 30-second-class grants, distinct attached frame, epoch advancement, event handling, schedules, typing/message fanout, delivery-specific message ids, metadata echo, expiry close 4000, and reconnect through reopen. Use deterministic model substitutes initially. Exit when all structural realtime assertions pass against the recreation. [Realtime API](./03-api-realtime-memory.md)

## Phase 3 — Model-backed turn-taking

Implement speak/silence routing, media/skip overrides, memory-assisted context, Theory-of-Mind refinement, 1–5 bubble generation, and exact pacing math. Match stale-epoch no-charge behavior and semantic invariants without pinning prose. Exit when the full realtime suite passes repeatedly within an approved credit budget. [Core engine](./05-core-engine.md)

## Phase 4 — Social Memory

Implement ordered append, first-write-wins idempotency across identical and changed bodies, subject-centric extraction, contradiction handling, recall, ask, and thread-bank integration. Exit when live tests prove bank switching/preservation, empty scope, person attribution, ordering, original-body retention, and no duplicate replay. [Realtime API](./03-api-realtime-memory.md)

## Phase 5 — Social Learning and foresee

Implement exact profile and foresee schemas, bounded transcript normalization, safe voice-card rendering, modeled mental state/reaction, and refined replies. Preserve the plugin convention that learned style is refreshed independently from durable factual memory. Exit when schema/invariant checks pass for both sparse and rich transcripts. [Intelligence API](./04-api-intelligence-personas.md) [Plugin analysis](../research/plugin-analysis.md)

## Phase 6 — Observability and audit

Implement synchronous analyze, deterministic all-type aggregates, owner-scoped report storage, repository null absence, audit parsing limits, first-write launch, staged nullable projection, and free terminal polling. Do not invent a public report linkage from analyze while production exposes none. Exit when evidence ids, error variants, progress order, repeat launch, and final section schemas pass. [Intelligence API](./04-api-intelligence-personas.md)

## Phase 7 — Personas

Implement full blueprint generation, conditional sampling, explicit null normalization, persona rendering, async repositories, enhancement with empty fields, aggregate constraint validation, diversity, and marginals. Exit when lifecycle, schema, seed preservation, pass/fail gate behavior, and free re-poll assertions pass. [Intelligence API](./04-api-intelligence-personas.md)

## Phase 8 — Hardening

Run both live suites against every release candidate. Add local tests for multi-tenant isolation, 402 reservation/replenishment, 403 policy, 429 throttling, crash recovery, queue duplication, prompt injection, retention, and provider failover; these are required engineering properties but not established production behavior. Run LoSoNA-style naive/norm-informed evaluations per candidate model. [Conformance strategy](./08-parity-and-open-questions.md) [LoSoNA digest](../research/paper-losona.md)

## Delivery discipline

Each phase MUST ship migrations, typed clients, examples, unit/integration tests, dashboards, rollback steps, and an explicit unresolved-behavior list. Acceptance MUST be based on live conformance plus deterministic internal tests. Generated prose MUST be checked by schema, grounding, and invariants rather than exact wording. [Conformance strategy](./08-parity-and-open-questions.md)