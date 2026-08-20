---
title: Protocol, Authentication, and Errors
description: Normative HTTP, authentication, endpoint-specific errors, idempotency, billing, and WSS contract.
tags: [humalike, specification, protocol, authentication]
status: complete
---
# Protocol, authentication, and errors

## HTTP and serialization

The origin MUST be configurable and default to `https://api.humalike.com`. Bodies are UTF-8 JSON. Actions and projections use POST; owner-scoped persona/report repositories use GET. Every captured response—success, 401, and 422 alike—carried a `content-type` beginning `application/json`, a non-empty `x-request-id`, and no rate-limit or `Retry-After` header; every compatible response MUST do the same. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

Timestamps MUST be ISO-8601 strings serialized as `YYYY-MM-DDTHH:MM:SS.ffffffZ` (microsecond precision, literal `Z`); the sole exception is the WSS `attached.server_time`, which uses `.ffffff+00:00`. IDs described as UUIDs MUST validate as RFC-4122 UUIDs (the suites accept versions 1–5). Opaque `respond.metadata` MUST be accepted and deeply echoed on every delivered bubble, and omitted metadata MUST be delivered as `null`. Unknown request fields, top-level or nested, MUST be silently ignored with a normal response: production returned 200 on `open_thread`, `submit_messages`, `record_event`, and `ingest` with extra fields present. [Realtime evidence](../research/tested-realtime-memory.md)

## Authentication and authorization

Every public route MUST require `Authorization: Bearer <token>`. Missing authorization, malformed schemes, bare `Bearer`, and invalid `ak_` values returned the exact response below on every probed route (all nine realtime and memory routes) and MUST return HTTP 401. [Realtime evidence](../research/tested-realtime-memory.md)

```json
{"error":{"code":"UNAUTHORIZED","message":"missing or invalid credentials"}}
```

Keys MUST be stored as hashes or HMAC lookup values and MUST never enter logs. Authentication yields an internal owner principal; every repository query and command MUST apply that owner. Valid-but-forbidden 403 behavior is documented but was not exercised. [Documented surface](../research/docs-api-surface.md)

## Error shapes are route-specific

There is no single production error schema beyond the outer `{error:{code,message,details?}}` shape, and the outer object has exactly one key. Implementations MUST serialize errors by endpoint and failure class. Request-validation `details[].loc` MUST NOT carry a leading `"body"` segment (a stock FastAPI/Pydantic serializer emits one and fails the suites); observed `type` values are `uuid_parsing`, `too_short`, `too_long`, `string_too_long`, `string_too_short`, and `literal_error`. [Intelligence evidence](../research/tested-intelligence-personas.md)

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
| Malformed id on any repository `by-id` route (Report, Population, Enhancement, Evaluation) | 400 exactly `{error:{code:"VALIDATION_ERROR",message:"invalid id"}}`—no `details` key. [Intelligence evidence](../research/tested-intelligence-personas.md) |
| Unparsable audit text | 400 `message:"no messages could be read from this text"`, `details:[{field:"raw_text",message:"no messages detected"}]`. [Intelligence evidence](../research/tested-intelligence-personas.md) |
| More than 250 parsed audit messages | 400 `message:"This transcript has <n> messages; the audit accepts at most 250."`, `details:[{field:"raw_text",message:"over the 250-message cap"}]`. [Intelligence evidence](../research/tested-intelligence-personas.md) |
| Audit text over the ~32,768-token budget | 400 `message:"This paste is too large to read: about <n> tokens, and the audit accepts about 32,768. Send at most 250 messages."`, `details:[{field:"raw_text",message:"at most ~32768 tokens allowed"}]`. [Intelligence evidence](../research/tested-intelligence-personas.md) |
| Audit launch with a nonparticipant | 400 `message:"agent_name must be one of the transcript's speakers"`, `details:[{field:"agent_name",message:"'<name>' never speaks"}]`. [Intelligence evidence](../research/tested-intelligence-personas.md) |
| Unknown `run_id` on audit launch or projection | 400 `message:"unknown run"`, `details:[{field:"run_id",message:"no such run"}]`; a malformed `run_id` is instead 422 `uuid_parsing`. [Intelligence evidence](../research/tested-intelligence-personas.md) |
| Missing repository UUID | 200 with JSON `null` for Report, Population, Enhancement, and Evaluation. [Intelligence evidence](../research/tested-intelligence-personas.md) |

A 402 means insufficient credits before billable work. The suites encountered no 402 in their reference runs, so the following are **documented defaults, not live-proven**: the 402 body is `{"error":{"code":"PAYMENT_REQUIRED","message":"insufficient credits"}}` and is returned before any work runs and without charge; 403 uses code `forbidden`; 502 uses code `UPSTREAM_ERROR`. A recreation MUST emit these documented shapes unless later live evidence contradicts them, and clients MUST branch on `error.code`, not message text. No rate-limit stress was authorized, so 429 body/header behavior is not normative. [Documentation corpus](../sources/docs/source.md) [Live conformance strategy](./08-parity-and-open-questions.md) [Documented surface](../research/docs-api-surface.md) [Live conformance strategy](./08-parity-and-open-questions.md)

## Idempotency and concurrency

Social Memory ingest MUST index idempotency by `(owner,key)`, not per scope: production replayed the first response for the same key sent to a different `scope_id` and stored nothing there. The first completed request stores its response and side effects. Every later use of the same key MUST return HTTP 200 with the first response, regardless of whether the body or scope is identical or changed; the later body MUST be silently ignored. Same-body replay MUST NOT duplicate stored facts. No replay-indicator header is required. [Realtime evidence](../research/tested-realtime-memory.md)

Thread reopen with an existing owner-scoped UUID rotates the WSS grant while retaining thread state. Audit launch is first-write-wins: a repeated launch returns 200, retains the first `agent_name`, reports `status:"queued"` while queued and `"completed"` afterwards, and does not restart work. Respond MUST compare and schedule against the epoch atomically; stale work returns exactly `{scheduled:[],superseded:true}` and adds no turn-taking or Theory-of-Mind charge. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

## Billing

A billable command SHOULD reserve/check credits before model work and capture after successful completion. Superseded, short-circuited, and terminal polling paths MUST not capture. The live suites prove terminal re-polling of completed audit/persona resources changes billed calls and credits by zero. Component prices observed during shared runs are informative, not stable public pricing. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)

## WebSocket protocol

`open_thread` returns a self-authenticating `wss://<origin-host>/v1/ws/turn-taking-thread?token=<payload>.<signature>` grant: exactly one query parameter named `token`, two base64url segments (43-character HMAC-SHA256-sized signature), and an `expires_at` 30.0 seconds after issuance (asserted within 25–35 s). A connection established before expiry remains open after expiry. A connection attempted about two seconds after expiry, or presenting a garbage token, completes the HTTP upgrade and then closes with WebSocket code `4000` and an empty reason. Reopening the thread issues a new grant for the same channel, and sockets attached through different grants receive identical frames and ids. [Realtime evidence](../research/tested-realtime-memory.md)

The initial `attached` frame has a distinct three-field shape; only later events use the five-field event envelope. The per-reply sequence MUST be exactly attached, typing true, one message per scheduled entry in position order, typing false—N+3 frames and nothing else. [Realtime API](./03-api-realtime-memory.md)

## Rate limiting

No sampled response exposed rate headers, and no stress test established quotas. A recreation MAY enforce internal limits, but successful responses MUST NOT invent production rate headers as part of compatibility. Exact 429 behavior remains an open question. [Realtime evidence](../research/tested-realtime-memory.md) [Intelligence evidence](../research/tested-intelligence-personas.md)