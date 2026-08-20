---
title: Protocol, Authentication, and Errors
description: Normative HTTP, authentication, endpoint-specific errors, idempotency, billing, and WSS contract.
tags: [humalike, specification, protocol, authentication]
status: complete
---
# Protocol, authentication, and errors

## HTTP and serialization

The origin MUST be configurable and default to `https://api.humalike.com`. Bodies are UTF-8 JSON. Actions and projections use POST; owner-scoped persona/report repositories use GET. Responses sampled across success and failure carried `content-type: application/json` and a non-empty `x-request-id`; every compatible response MUST do the same. No sampled response exposed rate-limit or `Retry-After` headers. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

Timestamps MUST be ISO-8601 strings. IDs described as UUIDs MUST validate as UUIDs. Opaque `respond.metadata` MUST be accepted and deeply echoed on every delivered bubble. Unknown-field behavior was not tested and MUST remain configurable rather than asserted as production truth. [Realtime evidence](../research/tested-realtime-memory.md)

## Authentication and authorization

Every public route MUST require `Authorization: Bearer <token>`. Missing authorization, malformed schemes, bare `Bearer`, and invalid `ak_` values returned the exact response below and MUST return HTTP 401. [Realtime evidence](../research/tested-realtime-memory.md)

```json
{"error":{"code":"UNAUTHORIZED","message":"missing or invalid credentials"}}
```

Keys MUST be stored as hashes or HMAC lookup values and MUST never enter logs. Authentication yields an internal owner principal; every repository query and command MUST apply that owner. Valid-but-forbidden 403 behavior is documented but was not exercised. [Documented surface](../research/docs-api-surface.md)

## Error shapes are route-specific

There is no single production error schema beyond the outer `{error:{code,message,details?}}` shape. Implementations MUST serialize errors by endpoint and failure class. [Intelligence evidence](../research/tested-intelligence-personas.md)

```ts
type RequestValidationError = {
  error:{
    code:"validation_failed";
    message:"request validation failed";
    details:{loc:(string|number)[];msg:string;type:string}[];
  };
};
type SemanticValidationError = {
  error:{
    code:"VALIDATION_ERROR";
    message:string;
    details?:{field:string;message:string}[];
  };
};
```

| Endpoint/failure | Status and tested body rule |
| --- | --- |
| Request-model failures across realtime, learning, foresee, audit prepare, and personas | 422 lowercase `validation_failed`; Pydantic-like `loc/msg/type`. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md) |
| `Report/by-id/not-a-uuid` | 400 uppercase `VALIDATION_ERROR`, message `invalid id`, no required details. [Intelligence evidence](../research/tested-intelligence-personas.md) |
| Unparseable or over-250-message audit input | 400 uppercase `VALIDATION_ERROR`; message describes the semantic failure. [Intelligence evidence](../research/tested-intelligence-personas.md) |
| Audit launch with a nonparticipant | 400 uppercase `VALIDATION_ERROR` plus `{field,message}` details. [Intelligence evidence](../research/tested-intelligence-personas.md) |
| Missing audit projection run | 400 uppercase `VALIDATION_ERROR`. [Intelligence evidence](../research/tested-intelligence-personas.md) |
| Missing repository UUID | 200 with JSON `null` for Report, Population, Enhancement, and Evaluation. [Intelligence evidence](../research/tested-intelligence-personas.md) |

A 402 means insufficient credits before billable work. The suites encountered no 402 in their final reference runs, so exact 402 body and replenishment behavior remain open. A 502 denotes an upstream dependency failure in documentation. No rate-limit stress was authorized, so 429 body/header behavior is not normative. [Documented surface](../research/docs-api-surface.md) [Live conformance strategy](./08-parity-and-open-questions.md)

## Idempotency and concurrency

Social Memory ingest MUST index idempotency by at least `(owner,route,key)`. The first completed request stores its response and side effects. Every later use of the same key MUST return HTTP 200 with the first response, regardless of whether the body is identical or changed; the later body MUST be silently ignored. Same-body replay MUST NOT duplicate stored facts. No replay-indicator header is required. [Realtime evidence](../research/tested-realtime-memory.md)

Thread reopen with an existing owner-scoped UUID rotates the WSS grant while retaining thread state. Audit launch is first-write-wins: a repeated launch returns 200, retains the first `agent_name`, and does not restart work. Respond MUST compare and schedule against the epoch atomically; stale work returns exactly `{scheduled:[],superseded:true}` and adds no turn-taking or Theory-of-Mind charge. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

## Billing

A billable command SHOULD reserve/check credits before model work and capture after successful completion. Superseded, short-circuited, and terminal polling paths MUST not capture. The live suites prove terminal re-polling of completed audit/persona resources changes billed calls and credits by zero. Component prices observed during shared runs are informative, not stable public pricing. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

## WebSocket protocol

`open_thread` returns a self-authenticating `wss://api.humalike.com/v1/ws/turn-taking-thread?...` grant with an observed lifetime near 30 seconds. A connection established before expiry remains open after expiry. A connection attempted about 1.5 seconds after expiry upgrades, then closes with WebSocket code `4000` and an empty reason. Reopening the thread issues a new grant for the same channel. [Realtime evidence](../research/tested-realtime-memory.md)

The initial `attached` frame has a distinct three-field shape; only later events use the five-field event envelope. Message order MUST be attached, typing true, one or more messages, typing false. [Realtime API](./03-api-realtime-memory.md)

## Rate limiting

No sampled response exposed rate headers, and no stress test established quotas. A recreation MAY enforce internal limits, but successful responses MUST NOT invent production rate headers as part of compatibility. Exact 429 behavior remains an open question. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)