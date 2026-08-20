---
title: Live-Tested Realtime and Memory API
description: Production API behavior proven by the runnable realtime test suite.
tags: [humalike, research, live-api, realtime, social-memory]
status: complete
---
# Live-tested realtime and memory API

## Test method

All findings were measured against `https://api.humalike.com` on 2026-08-20 by a live Node suite with no recorded responses. Every run creates unique thread and memory identifiers, makes real HTTP and WSS calls, and reads the bearer key only from the environment. The final run completed **52 assertions with 0 failures**. [Live runner](../tests/realtime/run.mjs) [WebSocket driver](../tests/realtime/ws-driver.mjs)

The runner called `usage-summary` first and last. The final account-wide delta was 21 billed calls and 608 credits: `turn-taking` +6/+6, `theoryofmind` +2/+8, `social-memory` +9/+9, and `personas` +4/+585. Personas belonged to the concurrent sibling run, so the attributable realtime-suite delta was **17 calls and 23 credits**. [Live runner](../tests/realtime/run.mjs)

## Protocol, identity, and headers

`whoami` accepts `{}` and returns exactly `{user_id:string}`. `usage-summary` accepts `{}` and returns exactly `{total_calls,total_credits,per_component:[{component,calls,credits}],daily_series:[{date,requests}]}` with integers and exactly seven weekday entries. [Live runner](../tests/realtime/run.mjs)

Missing authorization, `Basic nope`, bare `Bearer`, and an invalid `ak_` bearer all returned HTTP 401:

```json
{"error":{"code":"UNAUTHORIZED","message":"missing or invalid credentials"}}
```

[Live runner](../tests/realtime/run.mjs)

Schema failures returned HTTP 422 with lowercase `validation_failed`, message `request validation failed`, and detail entries containing exactly `loc`, `msg`, and `type`. Observed types were `uuid_parsing`, `too_short`, `too_long`, `string_too_long`, `literal_error`, and `string_too_short`; locations included `messages/0/content`. [Live runner](../tests/realtime/run.mjs)

Successful and error JSON responses exposed `content-type: application/json` and `x-request-id`. Sampled headers also included CloudFront `via`, `x-cache`, `x-amz-cf-id`, and `x-amz-cf-pop`, plus `server: uvicorn`; no rate-limit or `Retry-After` header appeared. This does not prove throttling is absent. [Live runner](../tests/realtime/run.mjs)

## Exact tested request schemas

The live suite exercised these JSON bodies (optional fields are shown where the suite sent them):

- `whoami` and `usage-summary`: `{}`. [Live runner](../tests/realtime/run.mjs)
- `open_thread`: `{}`; `{thread_id}`; and `{thread_id?,integrations:{social_signals:{channel_id?},social_memory:{memory_bank_id}}}`. [Live runner](../tests/realtime/run.mjs)
- `submit_messages`: `{thread_id,messages:[{sender,content,client_ts?,has_media?}],system_prompt?,skip_decide?}`. [Live runner](../tests/realtime/run.mjs)
- `record_event`: `{thread_id,type,sender,client_ts?}`. [Live runner](../tests/realtime/run.mjs)
- `respond`: `{thread_id,content,turn_epoch,system_prompt?,agent_name?,pacing:{reading_delay_ms,typing_wpm,max_typing_ms},metadata?}`. [Live runner](../tests/realtime/run.mjs)
- Social Memory `ingest`: `{scope_id,transcript:[{speaker,text}]}` plus `Idempotency-Key`; `recall`: `{scope_id,message:{speaker,text}}`; `ask`: `{scope_id,question}`. [Live runner](../tests/realtime/run.mjs)

Unknown request fields were not probed. The suite did probe invalid UUID, message cardinality 0 and 21, content 4001, sender 256, unknown event type, and empty memory question. [Live runner](../tests/realtime/run.mjs)

## Turn-taking HTTP

### Open and reopen

`open_thread` returned exactly `{thread,channel,realtime}`. `thread` had `id,user_id,created_at,updated_at`; `channel` was `turn-taking-thread/{thread_id}`; and `realtime` had `connect_url,expires_at`. The URL was `wss://api.humalike.com/v1/ws/turn-taking-thread?token=...`, with an observed TTL of about 30.1 seconds. [Live runner](../tests/realtime/run.mjs)

Reopening the same UUID preserved its id, advanced `updated_at`, and rotated the grant. Supplying memory bank B on reopen changed the integration; reopening again with integrations omitted preserved bank B. Distinct seeded bank-A and bank-B tokens proved only B was recalled. Invalid UUID produced 422 at `loc:["thread_id"]`, type `uuid_parsing`. [Live runner](../tests/realtime/run.mjs)

### Submit messages and events

`submit_messages` returned exactly `{decision,turn_epoch,tags,recalled_context}`. Both `skip_decide:true` and `has_media:true` returned `speak`; consecutive batches advanced the epoch exactly once each. A thread without integrations returned empty tags/context; the integrated thread returned memory containing the bank-B token. [Live runner](../tests/realtime/run.mjs)

Bounds returned 422: zero messages was `too_short`, 21 was `too_long`, and content length 4001 and sender length 256 were nested `string_too_long` details. A directly addressed modeled decision returned `speak`. Three strict side-chatter trials also returned `speak`, so `stay_silent` remains uncaptured. [Live runner](../tests/realtime/run.mjs)

Each `record_event` type (`typing_start`, `typing_stop`, `message_edited`) returned exactly `{tags:[]}`. An unknown type returned 422 `literal_error`. While WSS was attached, all three valid calls emitted no `turn_taking.signal`; `record_event` alone did not trigger that optional frame in this scenario. [Live runner](../tests/realtime/run.mjs) [WebSocket driver](../tests/realtime/ws-driver.mjs)

### Respond and pacing

Normal `respond` returned `{scheduled:[...],superseded:false}`. Entries contained exactly `id,created_at,updated_at,thread_id,content,position,deliver_at,status`; positions began at zero and times increased. Production materially rewrote the draft and, in the final run, substituted an unrelated four-digit verification code, so scheduled content is generated output rather than a faithful split. [Live runner](../tests/realtime/run.mjs)

With reading delay 500 ms, 120 WPM, and max typing 1500 ms, first delivery was creation plus reading delay plus `min(word_count / 120 * 60000,1500)`. Later bubbles added a fixed 200 ms inter-bubble gap plus capped typing time. Observed serialized timestamp arithmetic can drift by 1 ms (`1999` ms versus an expected `2000` ms), so the live assertion allows a tight ±10 ms tolerance around the formula. The representative inter-bubble spacing remains approximately 1700 ms; `max_typing_ms` excludes the gap. [Live runner](../tests/realtime/run.mjs)

After a newer batch advanced the epoch, the stale response was exactly HTTP 200 `{scheduled:[],superseded:true}`. Component-scoped usage snapshots showed no `turn-taking` or `theoryofmind` charge; one concurrent `social-memory` call appeared account-wide. [Live runner](../tests/realtime/run.mjs)

## WebSocket delivery

The handshake **does not** use the five-field event envelope:

```json
{"type":"attached","channel":"turn-taking-thread/[THREAD_UUID]","server_time":"[ISO_UTC]"}
```

Subsequent events used `{id,type,channel,ts,data}`. The complete captured type catalog was `attached`, `turn_taking.typing`, and `turn_taking.message`; no signal arrived. [Live runner](../tests/realtime/run.mjs)

Redacted ordered transcript:

```json
{"id":"evt_[REDACTED]","type":"turn_taking.typing","channel":"turn-taking-thread/[THREAD_UUID]","ts":"[ISO_UTC]","data":{"thread_id":"[THREAD_UUID]","typing":true}}
{"id":"evt_[REDACTED]","type":"turn_taking.message","channel":"turn-taking-thread/[THREAD_UUID]","ts":"[ISO_UTC]","data":{"message_id":"[DELIVERED_UUID]","thread_id":"[THREAD_UUID]","content":"I've got the realtime transport test. The first bubble confirms delivery, and the second one confirms ordering.","position":0,"sent_at":"[ISO_UTC]","metadata":{"test_run":"[RUN_ID]","nested":{"round_trip":true}}}}
{"id":"evt_[REDACTED]","type":"turn_taking.typing","channel":"turn-taking-thread/[THREAD_UUID]","ts":"[ISO_UTC]","data":{"thread_id":"[THREAD_UUID]","typing":false}}
```

Positions were zero-based and metadata round-tripped deeply unchanged. The WSS `message_id` was a UUID but **differed** from the scheduled HTTP `id`. Order was attached → typing true → messages → typing false. [Live runner](../tests/realtime/run.mjs) [WebSocket driver](../tests/realtime/ws-driver.mjs)

A pre-expiry socket remained open after expiry. A new connection about 1.5 seconds after expiry completed the upgrade, then immediately closed with code `4000` and empty reason; it was not rejected at HTTP upgrade. Reopening issued a fresh grant that attached to the same channel. [Live runner](../tests/realtime/run.mjs)

## Social Memory

`ingest` preserved a three-message ordered transcript and returned exactly `{ingested:3}`. Same-body replay with the same `Idempotency-Key` returned the same 200 body. **Contrary to the current specification, the same key with a different body also returned 200 and replayed `{ingested:3}`, not 409.** [Live runner](../tests/realtime/run.mjs)

Fresh-scope recall returned exactly `{context:""}`. After ingest, recall for Xena surfaced a code Yara stated about Xena and attributed it to Xena. `ask` returned that code; an ordering question returned blue-first and green-second. Assertions target these semantic invariants, not prose. Empty `ask.question` returned 422 with `loc:["question"]`, type `string_too_short`. [Live runner](../tests/realtime/run.mjs)

## Specification contradictions

- `attached` is `{type,channel,server_time}`, not `{id,type,channel,ts,data}`. [Live runner](../tests/realtime/run.mjs)
- Expired grants upgrade and close with code 4000 in the tested window. [Live runner](../tests/realtime/run.mjs)
- WSS `message_id` differs from scheduled HTTP `id`. [Live runner](../tests/realtime/run.mjs)
- Same idempotency key plus different ingest body replayed 200, not 409. [Live runner](../tests/realtime/run.mjs)
- `record_event` emitted no signal frame in the attached test. [Live runner](../tests/realtime/run.mjs)
- `max_typing_ms` excludes the fixed 200 ms bubble gap. [Live runner](../tests/realtime/run.mjs)

## Targeted closure experiments

### Signal frames: definitive negative

A fresh thread was opened with `integrations.social_signals.scope_id` set. The suite recorded `message_edited` before WSS attachment, then `typing_start`, `typing_stop`, and `message_edited` from multiple senders after attachment. It also submitted a modeled two-human batch while attached. Every event response and the submit response had `tags:[]`; no `turn_taking.signal` frame arrived before, during, or after the delivered reply. [Live runner](../tests/realtime/run.mjs)

The Hermes client's receive loop has explicit branches only for `turn_taking.message` and `turn_taking.typing`; it neither expects nor handles `turn_taking.signal`. Repository search found no signal-frame implementation elsewhere in the plugin. [Hermes WebSocket client](../sources/hermes-humalike-plugin/turn_taking/service.py)

This is a definitive negative across the requested integration, attachment-timing, event-type, sender, and submit-tag hypotheses. Production may have another undocumented trigger, but the documented inputs did not expose it. [Live runner](../tests/realtime/run.mjs)

### `stay_silent`: resolved

The modeled batch on the Social Signals thread contained two humans clearly addressing one another, with a lurker system prompt. Production returned the full response `{decision:"stay_silent",turn_epoch:1,tags:[],recalled_context:""}`. The permanent test validates the response schema and records the outcome without requiring the nondeterministic decision on every future run. Five additional engineered cases covered named human-to-human dialogue, `@someone-else`, a bare `ok thanks`, and an explicitly private exchange. [Live runner](../tests/realtime/run.mjs)

### Multi-bubble WSS metadata: resolved

A forced five-thought reply produced exactly five scheduled entries and five WSS message frames. Every frame echoed the nested metadata object unchanged, positions were `0,1,2,3,4`, and both scheduled and delivered arrays remained ordered. Local arrival offsets relative to HTTP `deliver_at` were `-22,-39,+328,+268,+189` ms in the measured run. [Live runner](../tests/realtime/run.mjs) [WebSocket driver](../tests/realtime/ws-driver.mjs)

All five delivered `message_id` UUIDs differed from their position-matched scheduled HTTP `id` values. The distinction is therefore systematic across a multi-bubble reply, not a one-bubble anomaly. [Live runner](../tests/realtime/run.mjs)

### Idempotency storage semantics: resolved

On a fresh scope, key K first ingested `Xavier works at Acme-693083`. Replaying K with the same body and then with changed body `Xavier works at Globex-693083` returned the original 200 `{ingested:1}` response both times. Recall and ask subsequently returned Acme and omitted Globex. Recall contained the unique Acme token once, with no duplication artifact from the same-body replay. The observed rule is **first body wins; later requests with the same key replay the first response regardless of body hash**. [Live runner](../tests/realtime/run.mjs)

### Follow-up run and billing

The expanded suite completed **60 assertions with 0 failures**. The account-wide first/last usage delta was 29 calls and 451 credits: `social-memory` +14/+14, `turn-taking` +9/+10, `theoryofmind` +2/+8, and concurrent sibling `personas` +4/+419. The attributable realtime-suite delta was therefore **25 calls and 32 credits**. [Live runner](../tests/realtime/run.mjs)

## Remaining unknowns

Only the production trigger for `turn_taking.signal` remains unknown after the definitive negative matrix above. `stay_silent`, multi-bubble metadata/order/timing/id relationships, and idempotency storage semantics now have live evidence and runnable assertions. Grant behavior remains bounded to the previously tested approximately 1.5-second post-expiry window. [Live runner](../tests/realtime/run.mjs)
