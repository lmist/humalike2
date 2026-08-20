---
title: Documented Humalike API Surface
description: Endpoint-by-endpoint synthesis of the Humalike public documentation corpus.
tags:
  - humalike
  - research
  - api
  - documentation
status: complete
---
# Documented Humalike API surface

## Transport and common contract

The public base URL is `https://api.humalike.com`. Every documented request uses `Authorization: Bearer <token>`; API keys are described as `ak_` credentials, and there are no unauthenticated public endpoints. JSON actions use `Content-Type: application/json`. Most failures use `{ "error": { "code", "message", "details?" } }`; `details` is endpoint-specific. The common status vocabulary is 400 processing/semantic validation, 401 missing or invalid credentials, 402 insufficient credits, 403 valid but disallowed, 422 malformed request, 502 upstream dependency failure, plus endpoint-specific lifecycle behavior. [Documentation corpus](../sources/docs/source.md)

The docs describe action-style POST routes and owner-scoped repository-style GET routes. Async jobs return an id, are polled until a terminal status, and may report a failed job inside HTTP 200. Billable actions reserve/check credits before work; uncovered calls return 402 and are not charged. `Idempotency-Key` is explicitly supported by Social Memory ingest, while turn-taking submit/respond and audit launch are documented as inherently retry-safe. [Documentation corpus](../sources/docs/source.md)

## Identity and usage

### `POST /v1/turn-taking/actions/whoami`

Request `{}`. Response `{ "user_id": string }`. Free preflight. Errors: 401 and 403. [Documentation corpus](../sources/docs/source.md)

### `POST /v1/credits/projections/usage-summary`

Request `{}`. Response: `total_calls: integer`, `total_credits: integer`, `per_component: [{component,calls,credits}]`, and exactly seven oldest-first UTC `daily_series: [{date,requests}]` points. The 30-day totals count only completed billed calls. Errors: 401, 403, 502. [Documentation corpus](../sources/docs/source.md)

## Turn-taking

### `POST /v1/turn-taking/actions/open_thread`

Optional request fields: `thread_id` UUID and `integrations`. `integrations.social_signals` optionally carries `scope_id`; `integrations.social_memory` carries `memory_bank_id` up to 255 characters, with legacy `scope_id` alias. Omission creates a UUID. Reopening the same owner-scoped id returns the existing thread and a new short-lived grant. Response contains `thread {id,user_id,created_at,updated_at}`, `channel`, and `realtime {connect_url,expires_at}`. Free. Errors: 401, 422. [Documentation corpus](../sources/docs/source.md)

The WebSocket URL is self-authenticating and short-lived. Frames use `{id,type,channel,ts,data}`. Event types are `turn_taking.message` with `{message_id,thread_id,content,position,sent_at,metadata}`, `turn_taking.typing` with `{thread_id,typing}`, and optional `turn_taking.signal` with `{thread_id,user_id,kind}`. Reopen after expiry or disconnect. [Documentation corpus](../sources/docs/source.md)

### `POST /v1/turn-taking/actions/submit_messages`

Request: `thread_id`; `messages` of 1–20 entries with `sender` 1–255, `content` 1–4000, optional ISO `client_ts`, optional `has_media`; optional `system_prompt` up to 100,000; optional `skip_decide`. Response: `decision` in `speak|stay_silent`, integer `turn_epoch`, `tags: string[]`, and `recalled_context: string`. `skip_decide` or any media message short-circuits to `speak` without billing; otherwise the decision is billable. The batch is still recorded and increments the epoch. Errors: 401, 402, 403, 422, 502. [Documentation corpus](../sources/docs/source.md)

### `POST /v1/turn-taking/actions/respond`

Request: `thread_id`, `content` 1–4000, matching integer `turn_epoch`; optional `system_prompt` up to 100,000; optional `agent_name` 1–255; optional `pacing {reading_delay_ms:0..30000, typing_wpm:(0,2000], max_typing_ms:(0,60000]}`; optional opaque `metadata` whose serialized size is at most 4096 bytes. Response: `scheduled` entries with `id,thread_id,content,position,deliver_at,status`, and `superseded`. A stale epoch returns HTTP 200 with `scheduled: []`, `superseded: true`, and no charge. A normal response refines the draft through Theory of Mind, splits it into 1–5 messages, and meters reply plus refinement. Errors: 401, 402, 403, 422, 502. [Documentation corpus](../sources/docs/source.md)

### `POST /v1/turn-taking/actions/record_event`

Request: `thread_id`, `type` in `typing_start|typing_stop|message_edited`, `sender` 1–255, optional ISO `client_ts`. Response `{ "tags": string[] }`; currently empty for these events. Free. Errors: 401, 403, 422. [Documentation corpus](../sources/docs/source.md)

## Social Memory

A `scope_id` is a caller-selected 1–255 character conversation id, partitioned by authenticated account. The service exposes no list, clear, or delete route. A reset therefore means choosing a new scope id. [Documentation corpus](../sources/docs/source.md)

### `POST /v1/social-memory/actions/ingest`

Request: `scope_id` and non-empty `transcript` of `{speaker:1..255,text:string}`. Response `{ "ingested": integer }`. It is a free plain append and supports `Idempotency-Key` replay. Errors: 401, 403, 422. [Documentation corpus](../sources/docs/source.md)

### `POST /v1/social-memory/actions/recall`

Request: `scope_id` and arriving `message {speaker,text}`. Response `{ "context": string }`; empty on an empty scope. Billable. Errors: 400 for unprocessable/oversized input, 401, 402, 403, 422, 502. [Documentation corpus](../sources/docs/source.md)

### `POST /v1/social-memory/actions/ask`

Request: `scope_id` and non-empty natural-language `question`. Response `{ "answer": string }`; empty on an empty scope. Billable. Same error set as recall. [Documentation corpus](../sources/docs/source.md)

## Social learning and observability

### `POST /v1/social-learning/actions/extract`

Request contains `transcript {messages:[Message]}` and may include a profile label. Messages carry stable `id`, `speaker`, `text`, and optional identity/channel/time/reply metadata. The output includes a norms/profile analysis and a ready-to-inject `prompt_block`. It is intended for a slow refresh cadence over a bounded recent window rather than every message. Billable; errors follow the common 400/401/402/422/502 model. [Documentation corpus](../sources/docs/source.md)

### `POST /v1/social-observability/actions/analyze`

Request: `agent_name`, `transcript {messages:[{id,speaker,text,user_id?,channel?,timestamp?,reply_to?}], source?}`, optional `focus`. IDs must be unique and the observed agent must be unambiguous. Response includes `health_score` in `[0,1]`, `summary`, interaction segmentation and totals, per-user reception/frustration/trend/evidence/confidence/distribution/key moments, and actionable findings with severity, evidence, recommendation, rewritten reply, and optional suggested component. The report is persisted. Calls may take 40–60 seconds and docs recommend a 120-second timeout. Errors: 400, 401, 402, 422, 502. [Documentation corpus](../sources/docs/source.md)

### `GET /v1/social-observability/repositories/Report/by-id/{id}`

Owner-scoped retrieval of a persisted analysis report by id. The repository projection returns the saved report or absence for a non-owned/nonexistent id, according to the docs' repository semantics. [Documentation corpus](../sources/docs/source.md)

## Audit workflow

### `POST /v1/social-observability/actions/audit_prepare`

Request hands over one raw transcript string. Response returns `run_id`, detected participants, and a guessed agent identity; the run remains parked. Preparation is billable, while abandonment incurs no later audit charge. The transcript has documented size limits. [Documentation corpus](../sources/docs/source.md)

### `POST /v1/social-observability/actions/audit_launch`

Request `{run_id,agent_name}` where `agent_name` exactly matches a participant. Response `{run_id,agent_name,status}` with first status `queued`. Repeating launch is a 200 no-op: no restart, rebilling, or identity change. Validation failures use 400; auth failure uses 401. [Documentation corpus](../sources/docs/source.md)

### `POST /v1/social-observability/projections/audit-run`

Request identifies the `run_id`. Response reports queued/running/completed state and, when complete, the full audit: reception analysis, missing context, turn-level risk, and rewrites. This is a projection POST rather than a repository GET. [Documentation corpus](../sources/docs/source.md)

## Theory of Mind

### `POST /v1/foresee/actions/foresee`

Request supplies conversation context and a drafted reply. The response models what the other person is thinking, predicts reaction/risk, and returns a refined reply designed to preserve intent while reducing likely damage. It is billable and should not be called before turn-taking `respond`, because `respond` already performs this pass. [Documentation corpus](../sources/docs/source.md)

## Personas

### `POST /v1/personas/actions/generate`

Request starts asynchronous grounded population generation from a prompt and population controls. The generated result includes a population blueprint (domain, ordered field definitions, distributions, dependencies, constraints) and personas with `persona_id`, flat `fields`, `system_prompt`, and `markdown`, plus diversity and marginal-fidelity reports. Initial response returns `{id,status:"pending"}`. [Documentation corpus](../sources/docs/source.md)

### `GET /v1/personas/repositories/Population/by-id/{id}`

Poll owner-scoped generation until `pending|running|succeeded|failed`. On success, `result` carries the population; on failure, `error` carries the stable category. [Documentation corpus](../sources/docs/source.md)

### `POST /v1/personas/actions/enhance`

Request `{persona:string}` starts asynchronous expansion of an existing persona into a complete persona object/system prompt. Initial response `{id,status:"pending"}`. [Documentation corpus](../sources/docs/source.md)

### `GET /v1/personas/repositories/Enhancement/by-id/{id}`

Poll until `succeeded` with `persona` or `failed` with `error`; ownership mismatch/nonexistence follows repository absence semantics. [Documentation corpus](../sources/docs/source.md)

### `POST /v1/personas/actions/validate`

Request `personas` and optional source `blueprint`. It queues deterministic schema/constraint and batch checks. Initial response `{id,status:"pending"}`. The quality verdict is not the job status: a completed evaluation can have `result.passed:false`. Errors documented: 401, 402, and 422 `validation_failed`. [Documentation corpus](../sources/docs/source.md)

### `GET /v1/personas/repositories/Evaluation/by-id/{id}`

Poll `pending|running|succeeded|failed`. Success result contains overall `passed`, batch gates, per-persona scorecards, and optional diversity/marginals. Each gate has `name,passed,score,detail`. Job failure is still represented as a terminal resource body rather than a transport failure. [Documentation corpus](../sources/docs/source.md)

## Documentary caveats

The prose-oriented export does not expose a formal OpenAPI schema, and some `ParamField` blocks omit field names in the text conversion. Exact generated-persona and foresee nested shapes should therefore be treated as best-effort unless live conformance coverage is added. Error-code casing is inconsistent even within docs (`VALIDATION_ERROR` versus `validation_failed`), which live probing confirms is not cosmetic. [Documentation corpus](../sources/docs/source.md)