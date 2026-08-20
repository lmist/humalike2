---
title: Humalike API Recreation Specification
description: Index and normative scope for a clean-room compatible Humalike API implementation.
tags:
  - humalike
  - specification
  - index
status: complete
---
# Humalike API recreation specification

## Purpose

This specification defines a clean-room service compatible with the documented and observed Humalike public API as of 2026-08-20. “MUST,” “SHOULD,” and “MAY” are normative. Where documentation and production differ, production fixtures control exact transport behavior and the discrepancy is explicit. [Research index](../research/index.md)

## Documents

1. [Product and domain model](./01-product-and-domain.md) — product surface, callers, concepts, entity ownership, and lifecycle.
2. [Protocol, authentication, and errors](./02-protocol-auth-errors.md) — HTTP conventions, bearer authorization, idempotency, pagination, streaming, and error compatibility.
3. [Realtime and memory API reference](./03-api-realtime-memory.md) — identity, usage, turn-taking, WebSocket, and Social Memory endpoints.
4. [Intelligence and personas API reference](./04-api-intelligence-personas.md) — Social Learning, Theory of Mind, observability, audit, persona generation/enhancement/validation, and repositories.
5. [Core engine design](./05-core-engine.md) — HUMA and LoSoNA algorithms mapped onto API behavior.
6. [System architecture](./06-system-architecture.md) — services, stores, queues, model serving, security, reliability, and capacity.
7. [Implementation plan](./07-implementation-plan.md) — phased milestones and delivery order.
8. [Parity validation and open questions](./08-parity-and-open-questions.md) — golden fixtures, differential tests, acceptance gates, and unresolved behavior.

## Evidence

The local [source catalog](../sources/index.md) preserves the docs, both paper bundles, plugin source, and redacted production fixtures. Distilled analyses live in the [research index](../research/index.md). No secret is part of this corpus.