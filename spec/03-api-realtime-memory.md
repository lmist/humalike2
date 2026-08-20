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

Body `{}`. Success is exactly `{user_id:string}` with a non-empty id. [Realtime evidence](../research/tested-realtime-memory.md)

### `POST /v1/credits/projections/usage-summary`

```ts
type UsageSummary={
  total_calls:number; total_credits:number;
  per_component:{component:string;calls:number;credits:number}[];
  daily_series:{date:"Mon"|"Tue"|"Wed"|"Thu"|"Fri"|"Sat"|"Sun";requests:number}[];
};
```

All counts are nonnegative integers and `daily_series` has exactly seven entries, oldest first, covering the last seven UTC days with zero-filled days. The component slugs are exactly `personas`, `social-learning`, `social-memory`, `social-observability`, `theoryofmind`, and `turn-taking`; the conformance suites key their billing assertions on these names. [Realtime evidence](../research/tested-realtime-memory.md) [Documented surface](../research/docs-api-surface.md)

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

The response keys are exact. `channel` MUST equal `turn-taking-thread/{thread.id}`. Omitted id creates a UUID; a caller-supplied unused UUID creates a thread with that id. Reopening preserves the id, strictly increases `updated_at`, and rotates the grant with a strictly later `expires_at`. Supplying a new memory bank changes it; subsequently omitting integrations preserves the selected bank. Invalid UUID returns the request-validation shape at `loc:["thread_id"]`, type `uuid_parsing`. Unknown fields are ignored. [Realtime evidence](../research/tested-realtime-memory.md)

`realtime.connect_url` MUST be `wss://<origin-host>/v1/ws/turn-taking-thread?token=<payload>.<signature>`: exactly one query parameter named `token`, whose value is two base64url segments (a 43-character HMAC-SHA256-sized signature). `expires_at` MUST be 30.0 seconds after issuance; the suites accept 25–35 s. [Realtime evidence](../research/tested-realtime-memory.md)

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

`messages` accepts 1–20 entries; sender is 1–255 characters and content 1–4000, with the upper bounds accepted and 0/21 entries, 256, and 4001 rejected (`too_short`, `too_long`, `string_too_long`). A fresh thread's first accepted batch returns `turn_epoch:1`; `record_event` calls do not advance the epoch; every accepted batch advances it by exactly one. `skip_decide:true` or any `has_media:true` short-circuits to `speak` without a modeled decision, but on a memory-integrated thread `recalled_context` is still populated from the configured bank. The captured silence response is exactly `{decision:"stay_silent",turn_epoch,tags:[],recalled_context:""}`. Unknown top-level and nested fields are ignored. [Realtime evidence](../research/tested-realtime-memory.md)

Social Signals is documented but not exhibited. With the integration configured, before and after WSS attachment, across all documented event types and a two-human modeled batch, responses still had empty `tags` and no signal frame arrived. Implementations MUST return `tags:[]` for these triggers and MUST NOT claim a `SignalData` wire contract. Another undocumented trigger may exist. [Realtime evidence](../research/tested-realtime-memory.md)

### `POST /v1/turn-taking/actions/record_event`

```ts
type RecordEventRequest={
  thread_id:string;
  type:"typing_start"|"typing_stop"|"message_edited";
  sender:string; client_ts?:string;
};
type RecordEventResponse={tags:string[]};
```

Each documented event MUST return exactly `{tags:[]}` (deep-equal). An unknown type produces 422 lowercase request validation at `loc:["type"]`, type `literal_error`. Events are free and do not touch the epoch. [Realtime evidence](../research/tested-realtime-memory.md)

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
  deliver_at:string;status:"scheduled";created_at:string;updated_at:string;
};
type RespondResponse={scheduled:ScheduledMessage[];superseded:boolean};
```

A current epoch returns 1–5 zero-based scheduled entries with strictly increasing delivery times and may materially rewrite the draft. A draft with more than five natural bubbles MUST be merged down to at most five with all content preserved, never truncated. Every entry has `status:"scheduled"`, `thread_id` equal to the request, non-empty `content`, and `updated_at` equal to `created_at`. `created_at` is stamped per entry at scheduling time (entries are monotone and within 5 ms of each other), not shared. A stale epoch returns HTTP 200 exactly `{scheduled:[],superseded:true}` without turn-taking or Theory-of-Mind billing. [Realtime evidence](../research/tested-realtime-memory.md)

Pacing is fully determined. With `words_i` the whitespace-token count of bubble `i`:

```text
typing_i   = min(max_typing_ms, max(500, words_i / typing_wpm * 60000))
deliver_0  = created_at_0 + reading_delay_ms + typing_0
deliver_i  = deliver_{i-1} + 200 + typing_i        (i ≥ 1)
```

The 500 ms typing floor and the fixed 200 ms inter-bubble gap are mandatory; `max_typing_ms` caps typing only and excludes the gap. When `pacing` or any of its members is omitted, the defaults MUST be `reading_delay_ms=0`, `typing_wpm=150`, and `max_typing_ms=8000`. Comparisons against serialized production timestamps MUST allow ±10 ms drift (1 ms has been observed). [Realtime evidence](../research/tested-realtime-memory.md)

## WebSocket frames

Connect to `realtime.connect_url` without an additional bearer header. The first frame MUST be:

```ts
type AttachedFrame={
  type:"attached";
  channel:string;
  server_time:string; // .ffffff+00:00 offset form
};
```

It MUST NOT be wrapped in the event envelope. Subsequent frames use:

```ts
type EventFrame<T>={id:string;type:string;channel:string;ts:string;data:T}; // id = "evt_" + 32 lowercase hex
type TypingData={thread_id:string;typing:boolean};
type MessageData={
  message_id:string;thread_id:string;content:string;position:number;
  sent_at:string;metadata:Record<string,unknown>|null;
};
type TypingFrame=EventFrame<TypingData>&{type:"turn_taking.typing"};
type MessageFrame=EventFrame<MessageData>&{type:"turn_taking.message"};
```

The per-reply sequence MUST be exactly attached → typing `true` → one message per scheduled entry in position order → typing `false` (N+3 frames, nothing else). `channel` on every frame equals the thread channel. Every message position is zero-based; every bubble echoes the full request metadata unchanged, or `null` when the request omitted it. Each WSS `message_id` is a UUID generated for delivery and MUST differ from the position-matched HTTP scheduled `id`. Multiple sockets attached to one channel through different grants MUST receive identical frames with identical event ids and message ids. Observed `sent_at` trailed `deliver_at` by 6–251 ms and `ts` trailed `sent_at` by about 10 ms; implementations SHOULD deliver within that envelope. No `turn_taking.signal` frame was observed under documented triggers. [Realtime evidence](../research/tested-realtime-memory.md)

An attached socket survives grant expiry. A late connection (about two seconds after expiry) or a garbage token completes the HTTP upgrade and then closes with code 4000 and an empty reason. Clients recover by reopening the same thread for a fresh grant. [Realtime evidence](../research/tested-realtime-memory.md)

## Social Memory

### `POST /v1/social-memory/actions/ingest`

```ts
type MemoryMessage={speaker:string;text:string};
type IngestRequest={scope_id:string;transcript:MemoryMessage[]};
type IngestResponse={ingested:number};
```

The transcript is ordered and non-empty; an empty transcript returns 422 `too_short` at `loc:["transcript"]`. `ingested` MUST equal the transcript length. `Idempotency-Key` is optional; without it every call appends. When present it is first-write-wins and indexed by `(owner,key)` across scopes: identical, changed-body, and different-`scope_id` replays all return the first 200 response, only the first body affects memory, and replay does not duplicate facts. Unknown fields are ignored. [Realtime evidence](../research/tested-realtime-memory.md)

### `POST /v1/social-memory/actions/recall`

Body `{scope_id:string,message:{speaker:string,text:string}}`. Success is exactly `{context:string}`; a fresh scope returns `{context:""}`. Retrieval MUST preserve subject attribution even when another speaker stated the fact. [Realtime evidence](../research/tested-realtime-memory.md)

### `POST /v1/social-memory/actions/ask`

Body `{scope_id:string,question:string}`. Success is exactly `{answer:string}`. Answers MUST be grounded in ingested content and preserve tested ordering facts. Empty question returns 422 lowercase request validation at `loc:["question"]`, type `string_too_short`. [Realtime evidence](../research/tested-realtime-memory.md)

## Non-endpoints

Do not expose public list, clear, or delete operations for threads, memory scopes, messages, or facts unless a later public contract establishes them. [Documented surface](../research/docs-api-surface.md)