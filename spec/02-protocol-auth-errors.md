---
title: Protocol, Authentication, and Errors
description: Normative HTTP, bearer authorization, error, idempotency, billing, and streaming contract.
tags:
  - humalike
  - specification
  - protocol
  - authentication
status: complete
---
# Protocol, authentication, and errors

## HTTP and serialization

The canonical origin MUST be configurable and default to `https://api.humalike.com`. Request and response bodies are UTF-8 JSON. Action and projection routes use POST; owner-scoped job repositories use GET. All timestamps MUST be ISO 8601 UTC. Unknown request fields SHOULD be rejected on strict contracts and preserved only for explicitly opaque `metadata`. No listed collection endpoint is paginated; therefore pagination is out of scope until a collection route exists. [Documented API surface](../research/docs-api-surface.md)

## Authentication

Every public endpoint MUST require:

```http
Authorization: Bearer <token>
```

The implementation MUST support `ak_` API keys and MAY support dashboard session tokens. Raw token material MUST be stored only as a salted hash or HMAC lookup key, compared in constant time, and never logged. Authentication produces `principal {owner_id,key_id,scopes,status}`. Missing, invalid, expired, or revoked credentials MUST return 401. A valid principal lacking route permission MUST return 403. [Documented API surface](../research/docs-api-surface.md)

Observed 401 compatibility body:

```json
{"error":{"code":"UNAUTHORIZED","message":"missing or invalid credentials"}}
```

[Live API experiments](../research/live-api-experiments.md)

## Authorization

Each command MUST inject `owner_id`; clients never submit it. Data access predicates MUST include owner id at the repository boundary, not only in handlers. Suggested scopes are `turn-taking`, `social-memory`, `social-learning`, `foresee`, `observability`, `personas`, and `usage:read`. Scope names are internal because public docs do not define them; a compatibility deployment MAY grant all current products to each customer key. [Documented API surface](../research/docs-api-surface.md)

## Errors

The canonical envelope is:

```ts
type ErrorEnvelope = {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
};
```

Handlers MUST emit JSON with an `x-request-id` response header. Validation errors SHOULD match production: HTTP 422, code `validation_failed`, message `request validation failed`, details as `[{loc:(string|number)[],msg:string,type:string}]`. Some docs state `VALIDATION_ERROR` or show `{field,message}`; the production fixture takes precedence for request-schema validation. Semantic/model processing failures MAY retain uppercase `VALIDATION_ERROR` where production parity later proves it. [Live API experiments](../research/live-api-experiments.md)

Status policy:

- 400: syntactically valid but unprocessable input, wrong audit participant, oversized semantic workload.
- 401: missing/invalid/expired/revoked bearer.
- 402: insufficient credits before billable work; no charge.
- 403: authenticated but forbidden.
- 404 or null/absence: only where later repository fixtures establish exact behavior.
- 422: schema/range/cardinality validation.
- 429: throttled; include `Retry-After` and stable error envelope.
- 502: upstream model/dependency failure; caller may retry with backoff.

[Documented API surface](../research/docs-api-surface.md)

## Idempotency and concurrency

Social Memory ingest MUST accept `Idempotency-Key`. Store `(owner_id,route,key,request_hash,response,status)` atomically. Same key/hash replays the response; same key/different hash MUST reject with 409. The observed replay returned the same 200 body but no replay header, so no header is required. [Live API experiments](../research/live-api-experiments.md)

Turn batches SHOULD deduplicate by a stable internal request hash/idempotency record, and respond MUST avoid duplicate scheduling. Audit launch MUST be a no-op after first launch. Thread opening with a supplied UUID is idempotent per owner. Epoch compare-and-schedule MUST be one transaction: stale replies return 200 `{scheduled:[],superseded:true}` and incur no charge. [Documented API surface](../research/docs-api-surface.md)

## Billing

A billable command MUST reserve/check credits before model execution, capture only after successful completion, and release reservation on failure. Free/short-circuited/superseded paths MUST bypass capture. Usage projection counts completed captures only. Respond captures two product units (reply plus Theory-of-Mind refinement) according to docs. [Documented API surface](../research/docs-api-surface.md)

## Streaming

`open_thread` returns a short-lived signed WSS URL. The signature MUST bind owner, channel, expiry, and a nonce; it MUST NOT expose the API key. New connections after expiry fail, while an attached connection MAY remain until disconnect. Frames use `{id,type,channel,ts,data}` and MUST preserve per-channel message order. The observed grant path was `/v1/ws/turn-taking-thread` with approximately 30-second connection TTL. [Live API experiments](../research/live-api-experiments.md)

Clients MUST reconnect by reopening the thread. The server SHOULD emit an `attached` handshake, typing toggles, one or more ordered message frames, and optional signal frames. Actual production frame fixtures remain an open parity item. [Plugin analysis](../research/plugin-analysis.md)

## Rate limiting

No sampled response exposed rate-limit headers, and no stress test was attempted. Implement token-bucket limits per key/account and expensive component, return 429 with `Retry-After`, and avoid inventing limit headers on successful responses until production behavior is observed. [Live API experiments](../research/live-api-experiments.md)