---
title: Early Live API Experiment Synthesis
description: Initial production observations reconciled with the exhaustive live conformance campaigns.
tags: [humalike, research, live-api, historical]
status: complete
---
# Early live API experiment synthesis

## Status

The initial conservative production probe established authentication, request ids, request-validation casing, basic thread/memory behavior, and server-side response rewriting. The later realtime and intelligence campaigns supersede it as the authoritative evidence because they exercise fresh live state through roughly 1,360 assertions. [Realtime evidence](./tested-realtime-memory.md) [Intelligence evidence](./tested-intelligence-personas.md)

No recorded response artifact is normative or required for validation. The committed suites call production directly, generate unique ids, and assert schemas and invariants. [Live conformance strategy](../spec/08-parity-and-open-questions.md)

## Conclusions retained

Missing and malformed credentials return the same 401 `UNAUTHORIZED` body; sampled JSON responses include `x-request-id`; request-model failures use lowercase `validation_failed` with `loc/msg/type`; scheduled reply text may materially differ from the draft; and Social Memory recall/ask returns generated but grounded prose. Each conclusion is now directly asserted by the exhaustive suites. [Realtime evidence](./tested-realtime-memory.md)

The intelligence campaign additionally established complete Social Learning, foresee, observability, audit, population, enhancement, and evaluation shapes, including endpoint-specific error variance and free terminal polling. [Intelligence evidence](./tested-intelligence-personas.md)

## Corrections made by later testing

The complete WSS handshake and delivery sequence is now captured; a late expired grant closes with code 4000; delivered message ids differ from schedule ids; Social Signals has a definitive negative under documented triggers; `stay_silent` has been observed; changed-body idempotency is first-write-wins with HTTP 200; and same-body replay does not duplicate memory. [Realtime evidence](./tested-realtime-memory.md)

Analyze does not expose a report id, audit progress uses nullable sections, enhanced personas may have empty fields, persona blueprints include extended fields and explicit nulls, constraint checks aggregate, and errors vary by endpoint. [Intelligence evidence](./tested-intelligence-personas.md)

## Ongoing role

This document is historical context only. New behavioral claims MUST enter through a live assertion, then the corresponding tested research digest, then the normative specification. [Specification index](../spec/00-index.md)