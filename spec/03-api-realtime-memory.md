---
title: Realtime and Memory API Reference
description: Normative endpoint schemas for identity, usage, turn-taking, WebSocket delivery, and Social Memory.
tags:
  - humalike
  - specification
  - api-reference
  - turn-taking
  - memory
status: complete
---
# Realtime and memory API reference

All routes require bearer authentication and use the [common protocol](./02-protocol-auth-errors.md). Field constraints below are normative. [Documented API surface](../research/docs-api-surface.md)

## Identity and usage

### `POST /v1/turn-taking/actions/whoami`

Body `{}`. 200 body `{user_id:string}`. Free. 401/403. [Live API experiments](../research/live-api-experiments.md)

### `POST /v1/credits/projections/usage-summary`

Body `{}`. 200 body:

```ts
type UsageSummary = {
  total_calls: number;
  total_credits: number;
  per_component: {component:string; calls:number; credits:number}[];
  daily_series: {date:"Mon"|"Tue"|"Wed"|"Thu"|"Fri"|"Sat"|"Sun"; requests:number}[]; // exactly 7, oldest first
};
```

The window is 30 days; daily points are UTC and zero-filled. Free read. 401/403/502. [Documented API surface](../research/docs-api-surface.md)

## Thread creation

### `POST /v1/turn-taking/actions/open_thread`

```ts
type OpenThreadRequest = {
  thread_id?: string; // UUID
  integrations?: {
    social_signals?: {scope_id?: string};
    social_memory?: {memory_bank_id?: string; scope_id?: string}; // values <=255
  };
};
type OpenThreadResponse = {
  thread:{id:string; user_id:string; created_at:string; updated_at:string};
  channel:string;
  realtime:{connect_url:string; expires_at:string};
};
```

Omitted id creates; supplied owner id reopens and rotates grant. Integrations are set on create and updated when supplied on reopen; omission preserves existing config. Free. 401/422. Production validation detail and WSS path are captured in [live experiments](../research/live-api-experiments.md).

## Decisions and events

### `POST /v1/turn-taking/actions/submit_messages`

```ts
type InboundMessage = {
  sender:string;       // 1..255
  content:string;      // 1..4000
  client_ts?:string;   // ISO 8601
  has_media?:boolean;
};
type SubmitRequest = {
  thread_id:string;
  messages:InboundMessage[]; // 1..20
  system_prompt?:string;     // <=100000
  skip_decide?:boolean;
};
type SubmitResponse = {
  decision:"speak"|"stay_silent";
  turn_epoch:number;
  tags:string[];
  recalled_context:string;
};
```

Record the batch and increment epoch exactly once. If `skip_decide` or any `has_media:true`, return `speak` without model billing. Otherwise run Router decision. If Social Signals disabled, tags are empty. If Social Memory disabled/unready, recalled context is empty. Billable only when a decision model runs. 401/402/403/422/502. [Documented API surface](../research/docs-api-surface.md)

### `POST /v1/turn-taking/actions/record_event`

```ts
type RecordEventRequest = {
  thread_id:string;
  type:"typing_start"|"typing_stop"|"message_edited";
  sender:string; // 1..255
  client_ts?:string;
};
type RecordEventResponse = {tags:string[]};
```

Free; 401/403/422. The current implementation may always return empty tags while persisting signal inputs. [Live API experiments](../research/live-api-experiments.md)

## Reply refinement and scheduling

### `POST /v1/turn-taking/actions/respond`

```ts
type RespondRequest = {
  thread_id:string;
  content:string;          // 1..4000
  turn_epoch:number;
  system_prompt?:string;   // <=100000
  agent_name?:string;      // 1..255
  pacing?:{
    reading_delay_ms?:number; // 0..30000
    typing_wpm?:number;       // >0..2000
    max_typing_ms?:number;    // >0..60000
  };
  metadata?:Record<string,unknown>; // serialized <=4096 bytes
};
type ScheduledMessage = {
  id:string; thread_id:string; content:string; position:number;
  deliver_at:string; status:string;
  created_at?:string; updated_at?:string; // observed production additions
};
type RespondResponse = {scheduled:ScheduledMessage[]; superseded:boolean};
```

Atomically compare epoch. If stale, return 200 superseded with no schedule/charge. Otherwise run Theory-of-Mind refinement in the agent voice, split into 1–5 bubbles, compute delivery times, persist, publish typing/message frames, and return schedule. The service may rewrite content materially. 401/402/403/422/502. [Live API experiments](../research/live-api-experiments.md)

## WebSocket

Connect to `realtime.connect_url` exactly as returned. Envelope:

```ts
type Frame = {id:string; type:string; channel:string; ts:string; data:unknown};
type MessageData = {message_id:string; thread_id:string; content:string; position:number; sent_at:string; metadata:object|null};
type TypingData = {thread_id:string; typing:boolean};
type SignalData = {thread_id:string; user_id:string; kind:string};
```

Types: `attached`, `turn_taking.message`, `turn_taking.typing`, `turn_taking.signal`. Metadata echoes verbatim on every bubble. Message position is zero-based. Reopen for a new grant after expiry/drop. [Plugin analysis](../research/plugin-analysis.md)

## Social Memory

### `POST /v1/social-memory/actions/ingest`

```ts
type MemoryMessage = {speaker:string; text:string}; // speaker 1..255; text non-empty
type IngestRequest = {scope_id:string; transcript:MemoryMessage[]}; // scope 1..255, transcript >=1
type IngestResponse = {ingested:number};
```

Append in order under `(owner,scope)`. Honor optional `Idempotency-Key`. Free. 401/403/422. [Live API experiments](../research/live-api-experiments.md)

### `POST /v1/social-memory/actions/recall`

Body `{scope_id:string,message:MemoryMessage}`. 200 `{context:string}`. Empty scope returns empty context. Use arriving speaker/text as retrieval query and attribute facts to their subjects, not necessarily their utterers. Billable. 400/401/402/403/422/502. [Documented API surface](../research/docs-api-surface.md)

### `POST /v1/social-memory/actions/ask`

Body `{scope_id:string,question:string}` with non-empty question. 200 `{answer:string}`; empty scope returns empty answer. Billable. 400/401/402/403/422/502. Production empty-question validation uses lowercase `validation_failed` and `loc/msg/type` detail. [Live API experiments](../research/live-api-experiments.md)

## Non-endpoints

Do not invent public list/delete/clear routes for threads, scopes, messages, or memory facts. No pagination contract exists because no collection endpoint is documented. [Documented API surface](../research/docs-api-surface.md)