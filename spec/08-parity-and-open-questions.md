---
title: Parity Validation and Open Questions
description: Differential validation strategy, acceptance gates, known discrepancies, and unresolved contracts.
tags:
  - humalike
  - specification
  - testing
  - open-questions
status: complete
---
# Parity validation and open questions

## Golden fixture strategy

Load each record in [raw production experiments](../sources/live/source.md), send the redacted request shape to the recreation, and assert method/path, status, required headers, envelope, field types, error casing, and invariants. Normalize timestamps, ids, request ids, account ids, WSS signatures, generated prose, and delivery times. For generated prose, assert semantic facts and schema rather than exact wording. [Live API experiments](../research/live-api-experiments.md)

Required exact gates:

- Missing/invalid bearer: 401 and exact observed error code/message.
- Valid whoami and seven-point usage schema.
- Invalid UUID/empty question: 422 lowercase `validation_failed` with `loc/msg/type` details.
- Open thread: owner fields, channel naming, WSS path/expiry class.
- Event: 200 `{tags:[]}`.
- Short-circuit submit: `speak`, epoch increment, empty tags, no billed model call.
- Normal submit: valid decision/epoch and memory field.
- Respond: schedule schema including observed timestamps, refinement allowed, `superseded:false`.
- Ingest and same-key replay: same 200 body without requiring replay header.
- Recall/ask: grounded answers with no invented person facts.

[Live API experiments](../research/live-api-experiments.md)

## Differential expansion

Against a dedicated low-cost account, add one probe per undocumented edge: wrong-owner repository ids, nonexistent ids, stale respond, repeated respond, reopen supplied nonexistent UUID, integration update semantics, empty Social Memory scope, duplicate message ids, max lengths ±1, 20/21 messages, metadata byte boundary, pacing bounds, idempotency same-key/different-body, audit launch repeat, failed async job body, and WSS attached/typing/message/signal frames. Never stress rate limits without explicit budget and permission. [Documented API surface](../research/docs-api-surface.md)

## LoSoNA behavioral parity

Run the 38-scenario protocol with three trials for naive and norm-informed prompts. Track majority accuracy, compliance, consistency, recovered failures, introduced regressions, scenario-bootstrap intervals, and human audit. A replacement is acceptable only if it improves norm compliance without a material regression/safety increase on naive successes. [LoSoNA paper digest](../research/paper-losona.md)

## System acceptance

- Cross-tenant access is impossible at repository and query layers.
- Every billable success has one capture; failed/superseded/short-circuit calls have none.
- Per-thread epochs and WebSocket messages preserve order under concurrency/restart.
- Async jobs are idempotent, observable, retryable, and terminal.
- P95 latency meets architecture targets at expected load.
- No credential or WSS grant appears in logs, fixtures, markdown, or commits.
- Markdown/API docs and typed schemas derive from one contract source.

## Confirmed discrepancies

Production uses lowercase `validation_failed` with Pydantic-like details where docs often state uppercase `VALIDATION_ERROR`. Production scheduled messages added `created_at` and `updated_at`. Production refinement changed trivial draft text. No rate headers were observed. [Live API experiments](../research/live-api-experiments.md)

## Open questions

1. Exact request/response schemas for `foresee`, full `extract` profile, persona generation controls/result wrappers, audit prepare/run, and report repository absence.
2. Exact defaults for service pacing, minimum typing delay, bubble splitting, decision model, strategy catalog, prompts, and tie-breaking.
3. Exact WSS `attached` frame and live typing/message/signal frames; reconnect behavior for already attached sockets.
4. Whether successful responses ever expose rate-limit headers and the actual quotas.
5. Exact same-key/different-body idempotency response and whether replay has an unobserved cache indicator.
6. Whether thread reopening with a supplied nonexistent UUID creates or rejects; docs prose is not fully consistent.
7. Repository behavior for nonexistent versus other-owner ids: null, 404, or another envelope.
8. Credit prices, reservation TTLs, component naming, and post-experiment usage delay.
9. Audit raw transcript field name/size limits and complete final result schema.
10. Persona blueprint field kinds, dependency expressions, sampling controls, diversity thresholds, and generation hyperparameters.
11. Data retention, deletion, residency, encryption, compliance, and customer export guarantees.
12. Models/providers, prompt versions, training/fine-tuning data, and safety classifiers used by production.
13. Device authorization routes' public support status and privileged gateway credential contract.

These unknowns MUST remain configuration or compatibility flags; they MUST NOT be silently invented as established production behavior. [Research index](../research/index.md)