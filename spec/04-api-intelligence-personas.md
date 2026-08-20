---
title: Intelligence and Personas API Reference
description: Normative schemas for learning, Theory of Mind, observability, audits, and personas.
tags:
  - humalike
  - specification
  - api-reference
  - personas
  - observability
status: complete
---
# Intelligence and personas API reference

All routes inherit the [common protocol](./02-protocol-auth-errors.md). Exact nested fields omitted by the prose export are marked compatibility-minimum and require fixture expansion. [Documented API surface](../research/docs-api-surface.md)

## Shared transcript

```ts
type TranscriptMessage = {
  id:string; speaker:string; text:string;
  user_id?:string; channel?:string; timestamp?:string; reply_to?:string;
};
type Transcript = {messages:TranscriptMessage[]; source?:string};
```

IDs MUST be unique when evidence references them. [Documented API surface](../research/docs-api-surface.md)

## Social Learning

### `POST /v1/social-learning/actions/extract`

Compatibility-minimum request `{transcript:Transcript}`. Response MUST include non-empty `prompt_block:string` when extraction succeeds and SHOULD include structured norms/profile fields described by docs. Use a bounded recent window, infer tone/register/verbosity/punctuation/emoji/local habits, and produce a safe prompt block that does not convert harmful behavior into imperative policy. 400/401/402/422/502. [Plugin analysis](../research/plugin-analysis.md)

## Theory of Mind

### `POST /v1/foresee/actions/foresee`

Request supplies transcript/conversation context plus drafted reply and optional agent identity prompt. Response MUST include predicted reception/risk and a refined reply preserving intent. The compatibility-minimum semantic contract is: read the room, identify likely interpretation and harm, then return an improved sendable reply. Exact nested field names remain fixture-gated. Billable; 400/401/402/422/502. Do not call this before `respond`, which embeds the same pass. [Documented API surface](../research/docs-api-surface.md)

## Reception analysis

### `POST /v1/social-observability/actions/analyze`

```ts
type AnalyzeRequest = {agent_name:string; transcript:Transcript; focus?:string};
type AnalyzeResponse = {
  id?:string;
  health_score:number; // 0..1
  summary:string;
  interactions:{type:"transactional"|"bonding"|"venting"|"banter"|"friction"|"hostile"; topic:string; participants:{name:string;user_id?:string;stance:string}[]; message_ids:string[]}[];
  interaction_totals:{type:string;count:number}[];
  per_user:{name:string;user_id?:string;reception:"engaged"|"neutral"|"bored"|"annoyed"|"churn_risk";frustration:number;trend:"improving"|"stable"|"declining";behaviors:string[];evidence:string[];confidence:number;note?:string;interaction_count:number;dominant_type:string;distribution:{type:string;count:number}[];key_moments:{label:string;type:string;message_ids:string[];agent_critique?:string}[]}[];
  findings:{issue:string;severity:"low"|"medium"|"high";affected_users:string[];evidence:string[];recommendation:string;before_message_id?:string;rewritten_reply?:string;suggested_component?:string;how_it_helps?:string;confidence:number}[];
};
```

Analyze exactly one conversation, persist report, preserve evidence ids, and use a long server/client timeout. 400/401/402/422/502. [Documented API surface](../research/docs-api-surface.md)

### `GET /v1/social-observability/repositories/Report/by-id/{id}`

Return the owner-scoped persisted analysis report. Exact absence representation is fixture-gated. [Documented API surface](../research/docs-api-surface.md)

## Full audit

### `POST /v1/social-observability/actions/audit_prepare`

Accept raw transcript text in the documented request field, parse speakers/messages, persist a prepared run, and return at least `{run_id,participants,agent_guess}`. Preparation is billable; nothing else runs before launch. Reject oversized/unparseable input per docs. [Documented API surface](../research/docs-api-surface.md)

### `POST /v1/social-observability/actions/audit_launch`

Body `{run_id:string,agent_name:string}`. Validate owner and exact participant membership. First success returns `{run_id,agent_name,status:"queued"}` and enqueues one audit. Repeat returns 200 current status/original agent without requeue or rebilling. Semantic errors are 400; auth 401. [Documented API surface](../research/docs-api-surface.md)

### `POST /v1/social-observability/projections/audit-run`

Body identifies `run_id`. Return current status and, on completion, reception report, missing-context analysis, per-turn risk, and rewrites. Exact nested result shape remains fixture-gated; never expose another owner's run. [Documented API surface](../research/docs-api-surface.md)

## Persona generation

### `POST /v1/personas/actions/generate`

Accept the documented generation prompt/population controls and enqueue a job. Return `{id:string,status:"pending"}`. The success result MUST provide:

```ts
type FieldSpec = {name:string;kind:string;parents:string[];categorical?:{weights:Record<string,number>};ordered_values?:string[];[k:string]:unknown};
type Constraint = {name:string;lhs:string;op:string;rhs:string};
type Blueprint = {domain:string;order:string[];fields:FieldSpec[];constraints:Constraint[]};
type Persona = {persona_id:string;fields:Record<string,string>;system_prompt:string;markdown:string};
type Population = {blueprint:Blueprint;personas:Persona[];diversity?:object;marginals?:object[]};
```

Generation MUST condition fields in blueprint order, enforce constraints, and expose quality diagnostics. 401/402/422/502 as documented. [Documented API surface](../research/docs-api-surface.md)

### `GET /v1/personas/repositories/Population/by-id/{id}`

Return owner-scoped `{id,status,result?,error?}` where status is `pending|running|succeeded|failed`. Polling is safe and free. [Documented API surface](../research/docs-api-surface.md)

## Persona enhancement

### `POST /v1/personas/actions/enhance`

Body `{persona:string}`. Enqueue and return `{id,status:"pending"}`. Enhancement preserves seed facts, fills a complete persona, and returns at least fields/system prompt/markdown compatible with generated personas. [Plugin analysis](../research/plugin-analysis.md)

### `GET /v1/personas/repositories/Enhancement/by-id/{id}`

Return `{id,status,persona?,error?}` until terminal. Poll every few seconds; plugin timeout is about five minutes. Exact absence body is fixture-gated. [Plugin analysis](../research/plugin-analysis.md)

## Persona validation

### `POST /v1/personas/actions/validate`

Body `{personas:Persona[],blueprint?:Blueprint}` with at least one persona. Enqueue deterministic gates and return `{id,status:"pending"}`. 401/402/422. [Documented API surface](../research/docs-api-surface.md)

### `GET /v1/personas/repositories/Evaluation/by-id/{id}`

```ts
type Gate={name:string;passed:boolean;score:number|null;detail:string};
type EvaluationResult={passed:boolean;gates:Gate[];scorecards:{persona_id:string;gates:Gate[]}[];diversity?:object;marginals?:object[]};
type EvaluationResource={id:string;status:"pending"|"running"|"succeeded"|"failed";result?:EvaluationResult;error?:string|object};
```

A succeeded job may report `result.passed:false`; do not conflate execution status with gate verdict. Constraints with missing/non-numeric fields are not applicable and pass with explanatory detail. [Documented API surface](../research/docs-api-surface.md)

## Installer device authorization

The plugin reveals `/v1/keys/actions/cli_create` and `/cli_poll`, but these depend on a privileged gateway bearer and are not part of the ordinary public recreation target. Implement them only as an optional RFC 8628-style extension after authorization requirements are known. [Plugin analysis](../research/plugin-analysis.md)