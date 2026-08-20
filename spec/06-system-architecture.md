---
title: System Architecture
description: Deployable service architecture, data model, queues, model serving, reliability, and security.
tags:
  - humalike
  - specification
  - architecture
status: complete
---
# System architecture

## Service topology

Deploy an API gateway/auth layer in front of bounded services: Identity/Credits, Turn-Taking, Realtime Delivery, Social Memory, Social Learning, Theory of Mind, Observability, Personas, and Job Orchestrator. Start as a modular monolith with explicit interfaces and one deployment for low operational cost; split realtime delivery and model workers first when load requires it. [Product and domain model](./01-product-and-domain.md)

## Data stores

- PostgreSQL: accounts, key hashes/scopes, credit ledger/reservations/captures, idempotency records, threads, epochs, inbound events, strategies, schedules, jobs, reports, persona resources, audit runs.
- Object storage: large raw transcripts, generated markdown, paper-independent customer artifacts, and immutable model traces under retention policy.
- Vector-capable PostgreSQL or dedicated vector store: message/fact embeddings and person-centric memory facts, always owner/bank partitioned.
- Redis: short-lived WSS grants/nonces, rate buckets, worker leases, pub/sub fanout, hot thread state.
- Durable queue: model jobs, memory extraction, audit stages, persona generation, schedule delivery, and retries with dead-letter queues.

[Core engine](./05-core-engine.md)

## Command path

Gateway authenticates and assigns request id; validates JSON; checks authorization/rate; invokes domain transaction. Billable commands reserve credits, enqueue or execute model work, persist outcome, capture charge, and return. Failures release reservation. Every write uses an outbox row in the same database transaction; an outbox relay publishes jobs/events to avoid dual-write loss. [Protocol specification](./02-protocol-auth-errors.md)

## Turn-taking path

`open_thread` is database-only plus signed grant issuance. `submit_messages` serializes by thread, appends batch, advances epoch, optionally extracts signals/memory, then short-circuits or invokes Router. Target p95: under 750 ms short-circuit and under 3 seconds modeled decision, consistent with the 0.6/1.9 second live observations. `respond` checks epoch, runs refinement/naturalization, stores schedules/outbox, and returns; target p95 under 5 seconds before scheduled delivery. [Live API experiments](../research/live-api-experiments.md)

A scheduler publishes due typing/message events to a per-thread ordered stream. Realtime gateways subscribe, enforce channel authorization, and fan out with backpressure. Delivery is at-least-once; frame ids let clients deduplicate. Ordering key is thread id. On restart, pending schedules are reloaded from the database. [Realtime API](./03-api-realtime-memory.md)

## Async jobs

Job rows carry `id,owner,type,status,stage,input_ref,result_ref,error,attempt,prompt_version,model_version,created_at,updated_at`. Workers claim with leases, heartbeat, checkpoint stage output, and use idempotent stage keys. Polling reads the durable projection, not worker memory. Audit launch uses compare-and-set from prepared to queued. [Intelligence API](./04-api-intelligence-personas.md)

## Model serving

Use a provider abstraction with per-stage capability requirements: structured output, context window, latency budget, and cost ceiling. Route fast decision/recall synthesis to low-latency models, refinement to a socially capable model, and batch analysis/personas to larger models. Cache only owner-safe deterministic intermediates. Embed messages asynchronously and maintain provider circuit breakers. [Core engine](./05-core-engine.md)

## Capacity and scaling

Partition thread/event/schedule work by thread id and memory by `(owner,bank)`. Horizontally scale stateless HTTP and WebSocket gateways. Bound model concurrency per account/provider and queue slow jobs separately from reply-path calls. Keep per-turn transcript windows bounded while retaining append-only source history. Apply backpressure before accepting work that cannot meet timeouts. [Plugin analysis](../research/plugin-analysis.md)

## Reliability

Use timeouts by class: approximately 5 seconds for database/free paths, 30 seconds for turn transport compatibility, 120 seconds for analysis, and minutes for async workers. Retry transient model/queue errors with exponential jitter; never blindly retry semantic 4xx. Persist idempotency and billing state before returning. Reconcile stuck credit reservations and scheduled messages. Expose health, queue lag, model error rate, schedule lateness, WSS connections, and parity test results. [Plugin analysis](../research/plugin-analysis.md)

## Security and privacy

Encrypt transport and data at rest; place secrets in a secret manager; redact bearer, WSS query grants, transcript text, emails, and account ids from routine logs. Enforce tenant predicates in repositories and row-level security as defense in depth. Scope signed WSS grants to one channel and expiry. Provide configurable retention/deletion internally even though the compatibility API exposes no delete routes. Audit administrative access and model-provider egress. [Protocol specification](./02-protocol-auth-errors.md)

## Observability

Propagate request id through database, queue, provider, and WebSocket frames. Store model stage latency/token/cost, selected strategy/scores, prompt and model versions, retrieval evidence ids, billing reservation/capture, and error taxonomy. Keep customer-visible generated claims evidence-linked internally to support debugging and audit reproducibility. [Core engine](./05-core-engine.md)