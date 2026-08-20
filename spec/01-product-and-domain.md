---
title: Product and Domain Model
description: Normative product surface, resources, ownership, and lifecycle for a Humalike-compatible service.
tags: [humalike, specification, domain-model]
status: complete
---
# Product and domain model

## Product promise

The service supplies group-chat turn decisions and paced delivery, local social-style extraction, person-centric memory, pre-send Theory-of-Mind refinement, reception analysis and audits, and persona generation, enhancement, and validation. [Documented surface](../research/docs-api-surface.md) A representative server-side caller opens one thread per agent context, refreshes learned style periodically, and consumes WSS message and typing events. [Plugin analysis](../research/plugin-analysis.md)

## Bounded contexts

- **Identity and credits:** principals, bearer keys, authorization, credit ledger, and usage projection. [Realtime evidence](../research/tested-realtime-memory.md)
- **Turn-taking:** owner-scoped thread, integrations, inbound batch, epoch, decision, schedule, WSS grant, and delivery events. [Realtime evidence](../research/tested-realtime-memory.md)
- **Social Memory:** owner/scope transcript, first-write idempotency record, subject facts, recall context, and direct answers. [Realtime evidence](../research/tested-realtime-memory.md)
- **Social Learning and Theory of Mind:** transcript-derived profile/prompt block and modeled reaction/refined reply. [Intelligence evidence](../research/tested-intelligence-personas.md)
- **Social Observability:** synchronous report, repository projection, prepared/launched audit, and progressively populated audit sections. [Intelligence evidence](../research/tested-intelligence-personas.md)
- **Personas:** population, enhancement, evaluation, blueprint, persona, diversity, marginal, gate, and scorecard resources. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Ownership and isolation

Every persisted resource MUST be keyed by an immutable owner derived from the verified bearer. Clients never submit an owner id. Thread reopen, memory scope access, audit runs, repositories, reports, and usage MUST apply the owner predicate at the repository boundary. Random repository UUIDs returned HTTP 200 JSON `null` in tested Report, Population, Enhancement, and Evaluation reads; implementations MUST preserve that absence behavior without disclosing another owner’s resource. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Resource lifecycles

A thread is created or reopened, receives ordered batches, and increments `turn_epoch` once per accepted batch. Reopen preserves state, updates supplied integrations, preserves omitted integrations, and rotates the short-lived WSS grant. A stale response is superseded atomically and schedules nothing. [Realtime evidence](../research/tested-realtime-memory.md)

Social Memory is append-only through the public surface. Reusing an ingest key MUST replay the first response and preserve the first body, even if a later body differs or targets a different scope; the key is owner-wide, not scope-wide. No public list, clear, or delete route is documented; callers reset by choosing a new scope. [Realtime evidence](../research/tested-realtime-memory.md) [Documented surface](../research/docs-api-surface.md)

`analyze` returns a complete report synchronously but exposes no report id, `Location`, or `x-report-id`. The public `Report/by-id` read exists, yet a newly analyzed report is not reachable through the tested flow; the recreation MUST reproduce the action response and repository absence behavior while treating linkage as unresolved. [Intelligence evidence](../research/tested-intelligence-personas.md)

Population, enhancement, and evaluation resources use `pending|running|succeeded|failed`. A succeeded evaluation can have `result.passed:false`. Audit preparation and launch are commands; audit projection progress is represented by nullable result sections becoming populated, not by required `status` or `stage` fields. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Timing classes

Identity, usage, thread open, events, ingest, and terminal repository polls are free in tested accounting. Model-backed operations consume credits. Observed terminal durations were about 20 seconds for audit, 52 seconds for population, 37 seconds for enhancement, and 3.5 seconds for evaluations; these are observations, not hard SLOs. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Compatibility principle

The implementation MUST match tested transport and state invariants exactly. Generated prose MUST be schema-valid, grounded in supplied/retrieved evidence, preserve required seed facts, and satisfy semantic assertions; it MUST NOT be compared by exact wording. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)