---
title: Humalike API Recreation Specification
description: Normative index for an end-to-end recreation of the tested Humalike API.
tags: [humalike, specification, index]
status: complete
---
# Humalike API recreation specification

## Purpose and authority

This specification defines a clean-room service compatible with the Humalike public API behavior tested on 2026-08-20. “MUST,” “SHOULD,” and “MAY” are normative. When sources conflict, the committed live suites and their tested research digests control observable transport behavior; documentation and paper digests supply untested surface and engine rationale only. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

Generated prose is nondeterministic. Compatibility therefore means exact status, envelope, field, lifecycle, ordering, billing, and timing invariants plus semantic grounding—not byte-equal model text. [Live conformance strategy](./08-parity-and-open-questions.md)

## Documents

1. [Product and domain model](./01-product-and-domain.md) — bounded contexts, ownership, resources, and lifecycles.
2. [Protocol, authentication, and errors](./02-protocol-auth-errors.md) — HTTP, bearer authorization, per-endpoint errors, idempotency, billing, and WSS rules.
3. [Realtime and memory API](./03-api-realtime-memory.md) — identity, usage, turn-taking, captured WSS frames, and Social Memory.
4. [Intelligence and personas API](./04-api-intelligence-personas.md) — Social Learning, foresee, observability, audit, and complete persona resources.
5. [Core engine design](./05-core-engine.md) — implementation pipelines grounded in HUMA, LoSoNA, and tested behavior.
6. [System architecture](./06-system-architecture.md) — deployable services, storage, queues, billing, delivery, and security.
7. [Implementation plan](./07-implementation-plan.md) — phased delivery with live conformance gates.
8. [Live conformance and open questions](./08-parity-and-open-questions.md) — the roughly 1,360-assertion live validation mechanism, the portable harness, and unresolved behavior.

## Evidence chain

The primary local source catalog preserves the documentation corpus, both paper bundles, and Hermes plugin source. [Source catalog](../sources/index.md) Production behavior is established by the two committed executable suites and their research digests. [Research index](../research/index.md) Secrets and WSS grants MUST remain outside tracked files. [Live conformance strategy](./08-parity-and-open-questions.md)