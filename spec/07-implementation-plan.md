---
title: Implementation Plan
description: Phased milestones for rebuilding and validating the Humalike-compatible service.
tags:
  - humalike
  - specification
  - implementation-plan
status: complete
---
# Implementation plan

## Phase 0 — Contract harness

Create typed schemas for every endpoint, canonical error serialization, request-id middleware, redaction tests, and a fixture runner that can replay the [redacted production observations](../sources/live/source.md). Freeze exact responses for auth, validation, open thread, event, short-circuit decision, reply scheduling, memory ingest/recall/ask, and usage. Exit when a stub server passes transport-level golden tests. [Parity plan](./08-parity-and-open-questions.md)

## Phase 1 — Identity, tenancy, credits

Implement bearer keys, account scoping, policy hooks, credit ledger/reservations/captures, usage projection, and whoami. Add 401/403/402 cases and key rotation/revocation internally. Exit when cross-tenant and billing atomicity tests pass. [Protocol specification](./02-protocol-auth-errors.md)

## Phase 2 — Turn state and realtime skeleton

Implement thread create/reopen, signed 30-second WSS grants, channel attachment, epoch advancement, record_event, schedule persistence, typing/message fanout, reconnect, and ordering/deduplication. Use deterministic Router/refiner stubs. Exit when interruption, stale respond, reconnect, metadata echo, and crash-recovery tests pass. [Realtime API](./03-api-realtime-memory.md)

## Phase 3 — Model-backed turn-taking

Implement strategy catalog/scoring, timeliness regularization, direct/media/skip overrides, Theory-of-Mind refinement, 1–5 bubble naturalization, pacing, and credit capture. Version prompts/models and record traces. Exit when latency SLOs and HUMA scenario tests pass. [Core engine](./05-core-engine.md)

## Phase 4 — Social Memory

Implement append/idempotency, subject-centric fact extraction, embeddings, contradiction handling, recall, ask, and thread bank integration. Exit when synthetic person-attribution, bank isolation, replay, empty-scope, and immediate-context fixtures pass. [Realtime API](./03-api-realtime-memory.md)

## Phase 5 — Social Learning and foresee

Implement attributed transcript normalization, bounded-window style/norm extraction, safe voice cards, and standalone Theory-of-Mind foresee. Validate that style is not duplicated into durable factual memory. Exit when plugin-shaped integration tests refresh/inject cards without blocking turns. [Plugin analysis](../research/plugin-analysis.md)

## Phase 6 — Observability and audit

Implement normalized analyze schema, deterministic aggregates, report persistence, raw audit parsing/preparation, explicit participant launch, idempotent staged job, and polling projection. Exit when evidence ids are valid, totals derive correctly, and abandoned prepared runs do not launch/bill. [Intelligence API](./04-api-intelligence-personas.md)

## Phase 7 — Personas

Implement blueprint generation, conditional sampling, constraints, persona rendering, async repositories, deterministic validation, diversity, and marginals. Add enhancement from seed text. Exit when lifecycle and quality-verdict distinctions match the spec. [Intelligence API](./04-api-intelligence-personas.md)

## Phase 8 — Norm adaptation and hardening

Build LoSoNA-compatible eval tooling, establish naive and norm-informed baselines, tune retrieval/injection per model, and block harmful-norm adaptation. Run load, chaos, privacy, cost, prompt-injection, tenant-isolation, and provider-failover tests. Exit only with parity dashboard green and safety sign-off. [LoSoNA paper digest](../research/paper-losona.md)

## Delivery discipline

Each phase ships migrations, typed clients, API examples, contract tests, dashboards, rollback plan, and an explicit list of unsupported unknowns. Do not block early phases on exact prose parity for undocumented nested schemas; gate those routes behind fixture completion and mark them experimental until resolved.