---
title: Live Humalike API Experiments
description: Ground-truth observations from conservative production API probes on 2026-08-20.
tags:
  - humalike
  - research
  - live-api
  - fixtures
status: complete
---
# Live Humalike API experiments

## Scope and safety

The production base URL `https://api.humalike.com` was probed on 2026-08-20 with the supplied `ak_` key using bearer authorization. Fifteen calls covered free reads/writes, one normal turn decision and reply, two Social Memory reads, and validation/auth failures. No delete, account mutation, bulk generation, audit, persona generation, rate-limit stress, or irreversible action was attempted. All persisted fixtures redact credentials, account identity, and WebSocket grant query. [Live fixtures](../sources/live/source.md)

## Authentication and headers

Missing and syntactically invalid credentials both returned HTTP 401 with identical `{error:{code:"UNAUTHORIZED",message:"missing or invalid credentials"}}`. A valid key returned 200 from `whoami`. Responses consistently exposed `Content-Type: application/json` and `x-request-id`; none of the sampled responses exposed rate-limit limit/remaining/reset or `Retry-After` headers. This does not prove that rate limiting is absent. [Live fixtures](../sources/live/source.md)

Initial usage was zero calls and zero credits with an empty component list and exactly seven zero-filled weekday points. The fixture intentionally records this pre-experiment snapshot, so it is not evidence that subsequent billable probes cost zero. [Live fixtures](../sources/live/source.md)

## Turn-taking observations

An invalid `thread_id` returned 422 with code `validation_failed`, message `request validation failed`, and structured detail `{loc:["thread_id"],msg,type:"uuid_parsing"}`. This differs from the docs' uppercase `VALIDATION_ERROR` label. [Live fixtures](../sources/live/source.md)

Opening a thread with Social Signals and Social Memory returned the documented thread/channel/realtime object. The observed WebSocket path was `/v1/ws/turn-taking-thread` with a redacted query grant and roughly 30-second expiry. Recording `typing_start` returned `{tags:[]}`. [Live fixtures](../sources/live/source.md)

A media/`skip_decide` batch returned `decision:"speak"`, epoch 1, empty tags, and empty recalled context in about 0.6 seconds. A normal directly addressed batch returned `speak`, epoch 2, and a non-empty memory summary of the preceding synthetic image test in about 1.9 seconds. This confirms that integrated memory writes/reads happen inside the turn-taking path. [Live fixtures](../sources/live/source.md)

`respond` accepted the matching epoch and aggressive low-delay pacing, then returned one scheduled message with `superseded:false` in about 2.8 seconds. The scheduled content was not the submitted draft: “Yes, I received…” became “I got your test message. How would you like to proceed?” This directly confirms server-side refinement/naturalization. The scheduled object also included undocumented-in-example `created_at` and `updated_at` fields. [Live fixtures](../sources/live/source.md)

The experiment did not connect to the WebSocket before its grant expired, so HTTP scheduling is observed but actual `attached`, typing, and message frame fixtures remain unverified. [Live fixtures](../sources/live/source.md)

## Social Memory observations

Ingesting two synthetic messages returned `{ingested:2}`. Repeating the same body with the same UUID `Idempotency-Key` again returned 200 and `{ingested:2}`. No replay-indicator header was observed; the equal body is consistent with replay but cannot independently prove storage was not duplicated. [Live fixtures](../sources/live/source.md)

Recall returned “Alice prefers jasmine tea. Bob is aware that Alice's favorite tea is jasmine.” Ask returned “Alice likes jasmine tea.” Both were grounded in the ingested messages and completed in about 1.0–1.1 seconds. An empty ask question returned 422 with lowercase `validation_failed` and detail `loc:["question"]`, `type:"string_too_short"`. [Live fixtures](../sources/live/source.md)

## Confirmed discrepancies and surprises

- Validation error code observed as lowercase `validation_failed`, while several docs tables say uppercase `VALIDATION_ERROR`.
- Validation `details` use Pydantic-like `loc/msg/type`, not the `{field,message}` shape shown in some examples.
- Scheduled messages include `created_at` and `updated_at` beyond the documented core fields.
- `respond` materially rewrote the draft even in a trivial test.
- Integrated Social Memory produced context from the immediately prior short-circuited media turn.
- No sampled response advertised rate-limit headers.

[Live fixtures](../sources/live/source.md)

## Fixture use

The raw JSON should seed contract tests for status, envelope shape, error casing, validation detail arrays, owner redaction, epoch progression, short-circuit decisions, refinement, idempotent replay response, and grounded memory outputs. Semantic text assertions must tolerate paraphrase; structural and invariant assertions should be exact. [Live fixtures](../sources/live/source.md)