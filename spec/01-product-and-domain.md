---
title: Product and Domain Model
description: Normative product surface, callers, entities, ownership, and lifecycle for a Humalike-compatible service.
tags:
  - humalike
  - specification
  - domain-model
status: complete
---
# Product and domain model

## Product promise

The service makes agents behave more like participants in human social systems. It provides: realistic group-chat turn timing; local conversational style extraction; person-centric memory; pre-send Theory-of-Mind refinement; reception analysis and full audits; and grounded persona population generation, enhancement, and validation. [Documented API surface](../research/docs-api-surface.md)

Primary callers are server-side agent runtimes, chat gateways, evaluation pipelines, dashboards, and batch observability jobs. Browser clients MUST NOT receive API keys. A representative runtime is the [Hermes integration](../research/plugin-analysis.md), which calls turn-taking per message, refreshes a voice card every fifth turn, and uses slow observability jobs off the reply path.

## Bounded contexts

- **Identity and credits:** account, API key/session token, authorization policy, credit ledger, usage projection.
- **Turn-taking:** thread, inbound message, turn epoch, decision, pacing plan, scheduled message, realtime channel, behavioral event/signal.
- **Social Memory:** owner-partitioned scope or memory bank, append-only transcript, extracted person facts, recall, question answer.
- **Social Learning:** attributed transcript, norms profile, prompt block/voice card.
- **Theory of Mind:** context, draft, predicted reception/risk, refined reply.
- **Social observability:** normalized transcript, interaction, user reception, finding, persisted report, asynchronous audit run.
- **Personas:** generation/enhancement/evaluation job, blueprint, field distribution/dependency/constraint, persona, gate, scorecard.

[Documented API surface](../research/docs-api-surface.md)

## Ownership and isolation

Every persisted entity MUST carry an immutable `owner_id` derived from the verified bearer token. Repository reads, thread reopening, Social Memory scope access, reports, audit runs, jobs, and usage MUST be owner-scoped. A missing or other-owner repository id SHOULD look absent rather than reveal existence. Memory scope identifiers are caller-selected and only unique inside an owner partition. [Documented API surface](../research/docs-api-surface.md)

## Lifecycles

A turn-taking thread is created/reopened, receives ordered batches, advances a monotonically increasing epoch, and schedules replies only against the current epoch. Reopening preserves state but rotates the realtime grant. Social Memory is append-only; no public delete/reset route exists, so a caller resets by choosing another scope. Reports are created by analysis and read later. Persona/audit resources are asynchronous state machines (`pending|running|succeeded|failed`, with audit-specific `prepared|queued|completed` vocabulary where documented). [Documented API surface](../research/docs-api-surface.md)

## Timing classes

- **Fast/free:** whoami, usage projection, open/reopen thread, record event, Social Memory ingest.
- **Fast/billable:** turn decision, response refinement/scheduling, recall, ask, foresee.
- **Slow synchronous:** extract and analyze; clients need long timeouts and should batch away from the reply path.
- **Asynchronous:** personas, enhancement, validation, and full audit.

[Documented API surface](../research/docs-api-surface.md)

## Compatibility principle

Exact HTTP status, field presence, casing, default, owner scoping, idempotency, and epoch behavior are compatibility requirements. Model-generated prose is semantically compatible when grounded and schema-valid; it need not be byte-identical. The [live fixtures](../research/live-api-experiments.md) show that even trivial drafts are rewritten, so deterministic text equality is not a valid general contract.