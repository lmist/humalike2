---
title: System Architecture
description: Deployable architecture for the tested Humalike-compatible service.
tags: [humalike, specification, architecture]
status: complete
---
# System architecture

## Topology

Start as a modular service with explicit Identity/Credits, Turn-Taking, Realtime Delivery, Social Memory, Social Learning, Theory of Mind, Observability, Personas, and Job Orchestration modules. HTTP and WSS may share a deployment initially; realtime fanout and model workers SHOULD scale independently when load requires it. This partition follows the public bounded contexts. [Domain model](./01-product-and-domain.md)

## Durable state

PostgreSQL SHOULD store accounts, key hashes, owner policies, credit reservations/captures, idempotency first results, threads/integrations/epochs, inbound batches/events, schedules, jobs, audit sections, reports, persona resources, and outbox records. Vector-capable storage SHOULD hold owner/scope-partitioned memory facts and embeddings. Redis or an equivalent ephemeral store MAY hold WSS grant nonces, rate state, worker leases, and fanout subscriptions. [Core engine](./05-core-engine.md)

Raw transcripts and model traces MAY use encrypted object storage under explicit retention policy. Public repository projections MUST read durable state rather than worker memory, and random/non-owned resource ids MUST not disclose existence. [Intelligence API](./04-api-intelligence-personas.md)

## Command transaction

The gateway authenticates, assigns `x-request-id`, validates route-specific JSON, and injects owner identity. A billable command reserves credits, performs or enqueues work, commits result plus outbox, captures the charge, and returns. Failures release reservations; short-circuited, superseded, and terminal polling paths bypass capture. [Protocol](./02-protocol-auth-errors.md)

Use an outbox in the same database transaction as schedules and job state so delivery/work publication cannot be lost between database commit and queue publish. Idempotency keys MUST protect both response replay and side effects. [Protocol](./02-protocol-auth-errors.md)

## Turn-taking and WSS

`open_thread` is a database transaction plus issuance of a 30-second HMAC-signed `token` grant (base64url payload and signature) scoped to one owner and channel. `submit_messages` serializes by thread, appends one batch, advances one epoch, updates integrated memory, and either short-circuits or runs the router. `respond` checks epoch, performs refinement/splitting, persists all bubbles, and commits delivery events before returning. [Realtime API](./03-api-realtime-memory.md)

A scheduler publishes due events on a stream ordered by thread. The WSS gateway first emits the distinct attached frame, then typing/message events. It generates delivery message ids independently from schedule ids and copies metadata to every bubble. An established connection does not depend on continued grant validity; late expired or invalid grants complete the upgrade and then close with code 4000, multiple sockets on one channel receive identical frames and ids, and reopening creates a new grant. [Realtime evidence](../research/tested-realtime-memory.md)

## Asynchronous resources

Population, enhancement, and evaluation jobs carry durable request echoes, nullable result/error, status, timestamps, and route-specific progress. Audit stores transcript, selected agent, and each nullable output section independently. Workers claim jobs with leases and idempotent stage keys; polling is a read-only projection and MUST not bill. [Intelligence API](./04-api-intelligence-personas.md)

Queue slow population/enhancement/audit work separately from reply-path decisions. The observed durations—about 52, 37, and 20 seconds respectively—justify long worker leases and multi-minute client timeouts, while evaluations completed in about 3.5 seconds. These observations are capacity inputs, not guaranteed SLOs. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Reliability and scaling

Partition turn delivery by thread and memory work by `(owner,scope)`. Bound model concurrency per owner and provider. Retry only transient provider/queue failures with jitter; do not retry semantic 4xx. Recover schedules from durable state after restart and reconcile abandoned credit reservations. [Protocol](./02-protocol-auth-errors.md)

Track request latency, model stage latency/cost, queue lag, schedule lateness, WSS connections/closes, epoch supersessions, idempotency replays, credit reservations/captures, and conformance suite results. Generated claims SHOULD retain internal evidence ids for debugging. [Core engine](./05-core-engine.md)

## Security and privacy

Use TLS, encryption at rest, secret management, hashed bearer lookup, owner predicates, and row-level security defense in depth. Redact bearer values, WSS query grants, account ids, and transcript bodies from routine logs. Scope each WSS grant to one owner/channel/expiry/nonce. Browser clients MUST not receive customer API keys. [Protocol](./02-protocol-auth-errors.md) [Plugin analysis](../research/plugin-analysis.md)