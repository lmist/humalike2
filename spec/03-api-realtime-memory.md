---
title: Realtime and Memory API Reference
description: Normative live-tested schemas for identity, usage, turn-taking, WSS delivery, and Social Memory.
tags: [humalike, specification, api-reference, turn-taking, memory]
status: complete
---
# Realtime and memory API reference

All routes require bearer authentication and follow the [protocol contract](./02-protocol-auth-errors.md). Exact shapes and invariants below come from the live realtime suite. [Realtime evidence](../research/tested-realtime-memory.md)

## Identity and usage

### `POST /v1/turn-taking/actions/whoami`

Body `{}`. Success is exactly `{user_id:string}`. [Realtime evidence](../research/tested-realtime-memory.md)

### `POST /v1/credits/projections/usage-summary`

```ts
type UsageSummary={
  total_calls:number; total_credits:number;
  per_component:{component:string;calls:number;credits:number}[];
  daily_series:{date:"Mon"|"Tue"|"Wed"|"Thu"|"Fri"|"Sat"|"Sun";requests:number}[];
};
```

All counts are nonnegative integers and `daily_series` has exactly seven entries. [Realtime evidence](../research/tested-realtime-memory.md)

## Thread creation and integrations

### `POST /v1/turn-taking/actions/open_thread`

```ts
type OpenThreadRequest={
  thread_id?:string;
  integrations?:{
    social_signals?:{scope_id?:string;channel_id?:string};
    social_memory?:{memory_bank_id:string};
  };
};
type OpenThreadResponse={
  thread:{id:string;user_id:string;created_at:string;updated_at:string};
  channel:string;
  realtime:{connect_url:string;expires_at:string};
};
```

The response keys are exact. `channel` MUST equal `turn-taking-thread/{thread.id}`. Omitted id creates a UUID. Reopening preserves the id, updates `updated_at`, and rotates the grant. Supplying a new memory bank changes it; subsequently omitting integrations preserves the selected bank. Invalid UUID returns the request-validation shape at `loc:["thread_id"]`. [Realtime evidence](../research/tested-realtime-memory.md)

## Decisions and events

### `POST /v1/turn-taking/actions/submit_messages`

```ts
type InboundMessage={sender:string;content:string;client_ts?:string;has_media?:boolean};
type SubmitRequest={
  thread_id:string; messages:InboundMessage[];
  system_prompt?:string; skip_decide?:boolean;
};
type SubmitResponse={
  decision:"speak"|"stay_silent";
  turn_epoch:number; tags:string[]; recalled_context:string;
};
```

`messages` accepts 1–20 entries; sender is at most 255 characters and content at most 4000. Every accepted batch advances the epoch once. `skip_decide:true` or `has_media:true` short-circuits to `speak`. The captured silence response was exactly `{decision:"stay_silent",turn_epoch,tags:[],recalled_context:""}`. Integrated memory returns context from the currently configured bank. [Realtime evidence](../research/tested-realtime-memory.md)

Social Signals is documented but not exhibited. With the integration configured, before/after WSS attachment, across all documented event types and a two-human modeled batch, responses still had empty `tags` and no signal frame arrived. Implementations MUST return the tested empty tags for these triggers and MUST NOT claim a `SignalData` wire contract. Another undocumented trigger may exist. [Realtime evidence](../research/tested-realtime-memory.md)

### `POST /v1/turn-taking/actions/record_event`

```ts
type RecordEventRequest={
  thread_id:string;
  type:"typing_start"|"typing_stop"|"message_edited";
  sender:string; client_ts?:string;
};
type RecordEventResponse={tags:string[]};
```

Each documented event returned exactly `{tags:[]}`. An unknown type produced 422 lowercase request validation at `loc:["type"]`. [Realtime evidence](../research/tested-realtime-memory.md)

## Reply refinement and scheduling

### `POST /v1/turn-taking/actions/respond`

```ts
type RespondRequest={
  thread_id:string; content:string; turn_epoch:number;
  system_prompt?:string; agent_name?:string;
  pacing?:{reading_delay_ms?:number;typing_wpm?:number;max_typing_ms?:number};
  metadata?:Record<string,unknown>;
};
type ScheduledMessage={
  id:string;thread_id:string;content:string;position:number;
  deliver_at:string;status:string;created_at:string;updated_at:string;
};
type RespondResponse={scheduled:ScheduledMessage[];superseded:boolean};
```

A current epoch returns 1–5 zero-based scheduled entries with strictly increasing delivery times and may materially rewrite the draft. A stale epoch returns HTTP 200 exactly `{scheduled:[],superseded:true}` without relevant billing. [Realtime evidence](../research/tested-realtime-memory.md)

For bubble `i`, let `typing_i=min(words_i/typing_wpm*60000,max_typing_ms)`. First delivery is `created_at + reading_delay_ms + typing_0`. Every later delivery follows the prior delivery by `200 + typing_i` milliseconds. Comparisons against serialized production timestamps MUST allow ±10 ms float/serialization drift (1 ms has been observed). `max_typing_ms` caps typing only; it excludes the fixed 200 ms inter-bubble gap. [Realtime evidence](../research/tested-realtime-memory.md)

## WebSocket frames

Connect to `realtime.connect_url` without an additional bearer header. The first frame MUST be:

```ts
type AttachedFrame={
  type:"attached";
  channel:string;
  server_time:string;
};
```

It MUST NOT be wrapped in the event envelope. Subsequent captured frames use:

```ts
type EventFrame<T>={id:string;type:string;channel:string;ts:string;data:T};
type TypingData={thread_id:string;typing:boolean};
type MessageData={
  message_id:string;thread_id:string;content:string;position:number;
  sent_at:string;metadata:Record<string,unknown>|null;
};
type TypingFrame=EventFrame<TypingData>&{type:"turn_taking.typing"};
type MessageFrame=EventFrame<MessageData>&{type:"turn_taking.message"};
```

Delivery order is attached → typing true → all ordered messages → typing false. Every message position is zero-based and every bubble echoes the full metadata object unchanged. Each WSS `message_id` is a UUID generated for delivery and MUST differ from the position-matched HTTP scheduled `id`; this held for all five bubbles in the multi-bubble test. Messages arrived near their HTTP `deliver_at` values. No `turn_taking.signal` frame was observed under documented triggers. [Realtime evidence](../research/tested-realtime-memory.md)

An attached socket survives grant expiry. A late connection in the tested window upgrades and closes with code 4000. Clients recover by reopening the same thread for a fresh grant. [Realtime evidence](../research/tested-realtime-memory.md)

## Social Memory

### `POST /v1/social-memory/actions/ingest`

```ts
type MemoryMessage={speaker:string;text:string};
type IngestRequest={scope_id:string;transcript:MemoryMessage[]};
type IngestResponse={ingested:number};
```

The transcript is ordered and non-empty. `Idempotency-Key` is optional but, when present, is first-write-wins: both identical and changed-body replays return the first 200 response; only the first body affects memory; identical replay does not duplicate facts. [Realtime evidence](../research/tested-realtime-memory.md)

### `POST /v1/social-memory/actions/recall`

Body `{scope_id:string,message:{speaker:string,text:string}}`. Success is exactly `{context:string}`; a fresh scope returns `{context:""}`. Retrieval MUST preserve subject attribution even when another speaker stated the fact. [Realtime evidence](../research/tested-realtime-memory.md)

### `POST /v1/social-memory/actions/ask`

Body `{scope_id:string,question:string}`. Success is exactly `{answer:string}`. Answers MUST be grounded in ingested content and preserve tested ordering facts. Empty question returns 422 lowercase request validation at `loc:["question"]`. [Realtime evidence](../research/tested-realtime-memory.md)

## Non-endpoints

Do not expose public list, clear, or delete operations for threads, memory scopes, messages, or facts unless a later public contract establishes them. [Documented surface](../research/docs-api-surface.md)