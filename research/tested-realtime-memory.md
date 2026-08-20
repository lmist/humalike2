---
title: Live-Tested Realtime and Memory API
description: Production API behavior proven by the runnable realtime test suite.
tags: [humalike, research, live-api, realtime, social-memory]
status: complete
---
# Live-tested realtime and memory API

## Test method

All findings were measured against `https://api.humalike.com` on 2026-08-20 by a live Node suite with no recorded responses. Every run creates unique thread and memory identifiers, makes real HTTP and WSS calls, and reads the bearer key only from the environment. The suite's target origin is `HUMALIKE_API_URL` (default production); WSS protocol and host expectations derive from it. The current run completes **83 assertions with 0 failures and 0 skips** across 96 captured responses (75×200, 13×401, 8×422). A 402 records per-block `SKIP` entries and exits with code 3 so a truncated run cannot read as green. [Live runner](../tests/realtime/run.mjs) [WebSocket driver](../tests/realtime/ws-driver.mjs)

The runner calls `usage-summary` first and last. In the cleanest current run the suite's own components were `turn-taking` 13 calls/15 credits, `theoryofmind` 6/24, and `social-memory` 13/13 — **32 calls and 52 credits** — with concurrent sibling `personas` activity excluded. The stale-epoch window delta was exactly 0 calls and 0 credits. [Live runner](../tests/realtime/run.mjs)

## Protocol, identity, and headers

`whoami` accepts `{}` and returns exactly `{user_id:string}`. `usage-summary` accepts `{}` and returns exactly `{total_calls,total_credits,per_component:[{component,calls,credits}],daily_series:[{date,requests}]}` with integers and exactly seven weekday entries. The observed component slug set is `personas`, `social-learning`, `social-memory`, `social-observability`, `theoryofmind`, and `turn-taking`. [Live runner](../tests/realtime/run.mjs)

Missing authorization, `Basic nope`, bare `Bearer`, and an invalid `ak_` bearer all returned HTTP 401, and every one of the nine routes returns the same exact body without a bearer:

```json
{"error":{"code":"UNAUTHORIZED","message":"missing or invalid credentials"}}
```

[Live runner](../tests/realtime/run.mjs)

Schema failures returned HTTP 422 with lowercase `validation_failed`, message `request validation failed`, and detail entries containing exactly `loc`, `msg`, and `type`. `loc` is never prefixed with `body`. Asserted types per location: `["thread_id"]`→`uuid_parsing`; `["messages"]` with 0 entries→`too_short`, with 21→`too_long`; `["messages",0,"content"]` (4001 chars) and `["messages",0,"sender"]` (256 chars)→`string_too_long`; `["type"]` unknown event→`literal_error`; `["question"]` empty→`string_too_short`; `["transcript"]` empty→`too_short`. [Live runner](../tests/realtime/run.mjs)

Every captured response — success, 401, and 422 — carried a non-empty `x-request-id`, a `content-type` beginning `application/json`, and zero rate-limit or `Retry-After` headers. Sampled headers also included CloudFront `via`, `x-cache`, `x-amz-cf-id`, and `x-amz-cf-pop`, plus `server: uvicorn`. Header absence does not prove throttling is absent. [Live runner](../tests/realtime/run.mjs)

Every HTTP timestamp and every WSS `ts`/`sent_at` is serialized as `YYYY-MM-DDTHH:MM:SS.ffffffZ` (microsecond precision, literal `Z`). The `attached.server_time` field alone uses `.ffffff+00:00`. [Live runner](../tests/realtime/run.mjs)

## Exact tested request schemas

The live suite exercised these JSON bodies (optional fields are shown where the suite sent them):

- `whoami` and `usage-summary`: `{}`. [Live runner](../tests/realtime/run.mjs)
- `open_thread`: `{}`; `{thread_id}`; and `{thread_id?,integrations:{social_signals:{scope_id?|channel_id?},social_memory:{memory_bank_id}}}`. [Live runner](../tests/realtime/run.mjs)
- `submit_messages`: `{thread_id,messages:[{sender,content,has_media?}],system_prompt?,skip_decide?}`. [Live runner](../tests/realtime/run.mjs)
- `record_event`: `{thread_id,type,sender,client_ts?}`. [Live runner](../tests/realtime/run.mjs)
- `respond`: `{thread_id,content,turn_epoch,system_prompt?,agent_name?,pacing?:{reading_delay_ms?,typing_wpm?,max_typing_ms?},metadata?}`. [Live runner](../tests/realtime/run.mjs)
- Social Memory `ingest`: `{scope_id,transcript:[{speaker,text}]}` with and without `Idempotency-Key`; `recall`: `{scope_id,message:{speaker,text}}`; `ask`: `{scope_id,question}`. [Live runner](../tests/realtime/run.mjs)

Unknown top-level fields (and an unknown nested field on submit) are silently ignored with HTTP 200 on `open_thread`, `submit_messages`, `record_event`, and `ingest`. Accept-side limits hold: exactly 20 messages, a 255-character sender, and 4000-character content all return 200 via `skip_decide:true`. Rejections were probed at invalid UUID, message cardinality 0 and 21, content 4001, sender 256, unknown event type, empty memory question, and empty ingest transcript. [Live runner](../tests/realtime/run.mjs)

## Turn-taking HTTP

### Open and reopen

`open_thread` returned exactly `{thread,channel,realtime}`. `thread` had `id,user_id,created_at,updated_at`; `channel` was `turn-taking-thread/{thread_id}`; and `realtime` had `connect_url,expires_at`. The URL is `wss://api.humalike.com/v1/ws/turn-taking-thread?token=<payload>.<signature>` with exactly one query key, `token`, whose value is two base64url segments (payload 186–188 characters, signature 43 characters, HMAC-SHA256-sized). The grant TTL measured from response end was 30,009–30,023 ms and is asserted within [25 s, 35 s]. [Live runner](../tests/realtime/run.mjs)

Reopening the same UUID preserved its id, strictly increased `updated_at`, and rotated the grant with a strictly later `expires_at`. Supplying memory bank B on reopen changed the integration; reopening again with integrations omitted preserved bank B. Distinct seeded bank-A and bank-B tokens proved only B was recalled. Invalid UUID produced 422 at `loc:["thread_id"]`, type `uuid_parsing`. [Live runner](../tests/realtime/run.mjs)

### Submit messages and events

`submit_messages` returned exactly `{decision,turn_epoch,tags,recalled_context}`. A fresh thread's first accepted batch returns `turn_epoch:1`, and `record_event` calls made before it do not advance the epoch. Both `skip_decide:true` and `has_media:true` returned `speak`; consecutive batches advanced the epoch exactly once each. A thread without integrations returned empty tags/context; the memory-integrated thread returned `recalled_context` containing the bank-B token, and it does so even on the `skip_decide`/`has_media` short-circuit paths. [Live runner](../tests/realtime/run.mjs)

A directly addressed modeled decision returned `speak`. Each `record_event` type (`typing_start`, `typing_stop`, `message_edited`) returned exactly `{tags:[]}` (deep-equal). An unknown type returned 422 `literal_error`. [Live runner](../tests/realtime/run.mjs) [WebSocket driver](../tests/realtime/ws-driver.mjs)

### Respond and pacing

Normal `respond` returned `{scheduled:[...],superseded:false}`. Entries contained exactly `id,created_at,updated_at,thread_id,content,position,deliver_at,status`; positions began at zero, times increased, `status` was the literal `"scheduled"` on every entry, and `updated_at` equalled `created_at`. `created_at` is per entry, not shared: entries are monotone and spread by at most ~60 µs (asserted ≤ 5 ms), and sit at roughly the response end of the call. Production materially rewrites the draft, so scheduled content is generated output rather than a faithful split. [Live runner](../tests/realtime/run.mjs)

The pacing model, asserted at ±10 ms across explicit and default runs, is:

```text
typing_i   = min(max_typing_ms, max(500, words_i / typing_wpm * 60000))
deliver_0  = created_at_0 + reading_delay_ms + typing_0
deliver_i  = deliver_{i-1} + 200 + typing_i        (i ≥ 1)
```

`words_i` is the whitespace-token count of the bubble. The **500 ms typing floor** is real: one word at 2000 WPM yields 500 ms, ten words yield 500 ms, and twenty-one words yield 630 ms. When `pacing` is omitted the defaults are `reading_delay_ms=0`, `typing_wpm=150` (exactly 400 ms per word), and `max_typing_ms=8000` (a 45-word bubble landed at exactly 8000 ms). A partial `pacing:{reading_delay_ms:0}` is accepted and omitted members take the same defaults. `max_typing_ms` caps typing only; the fixed 200 ms inter-bubble gap is outside it. Serialized timestamp arithmetic can drift by 1 ms, hence the ±10 ms tolerance. [Live runner](../tests/realtime/run.mjs)

After a newer batch advanced the epoch, the stale response was exactly HTTP 200 `{scheduled:[],superseded:true}`. Component-scoped usage snapshots showed no `turn-taking` or `theoryofmind` charge. [Live runner](../tests/realtime/run.mjs)

A six-paragraph draft under a "never merge" prompt is bounded to at most five bubbles by **merging**, not truncation: all six bracketed labels survived, once as three bubbles of two labels and once as five bubbles with the last two labels merged. [Live runner](../tests/realtime/run.mjs)

## WebSocket delivery

The handshake **does not** use the five-field event envelope:

```json
{"type":"attached","channel":"turn-taking-thread/[THREAD_UUID]","server_time":"[ISO_UTC]"}
```

Subsequent events used exactly `{id,type,channel,ts,data}` with `id` of the form `evt_` followed by 32 lowercase hex characters. The complete captured sequence for one reply is exactly `attached`, `turn_taking.typing` with `typing:true`, one `turn_taking.message` per scheduled entry in position order, then `turn_taking.typing` with `typing:false` — N+3 frames and nothing else. Typing `data` is exactly `{thread_id,typing}`; message `data` is exactly `{message_id,thread_id,content,position,sent_at,metadata}`. No signal frame arrived. [Live runner](../tests/realtime/run.mjs)

Redacted ordered transcript:

```json
{"id":"evt_[REDACTED]","type":"turn_taking.typing","channel":"turn-taking-thread/[THREAD_UUID]","ts":"[ISO_UTC]","data":{"thread_id":"[THREAD_UUID]","typing":true}}
{"id":"evt_[REDACTED]","type":"turn_taking.message","channel":"turn-taking-thread/[THREAD_UUID]","ts":"[ISO_UTC]","data":{"message_id":"[DELIVERED_UUID]","thread_id":"[THREAD_UUID]","content":"I've got the realtime transport test. The first bubble confirms delivery, and the second one confirms ordering.","position":0,"sent_at":"[ISO_UTC]","metadata":{"test_run":"[RUN_ID]","nested":{"round_trip":true}}}}
{"id":"evt_[REDACTED]","type":"turn_taking.typing","channel":"turn-taking-thread/[THREAD_UUID]","ts":"[ISO_UTC]","data":{"thread_id":"[THREAD_UUID]","typing":false}}
```

Positions were zero-based and metadata round-tripped deeply unchanged; when `metadata` is omitted from `respond`, every bubble carries `metadata:null`. The WSS `message_id` is a UUID that **differs** from the scheduled HTTP `id`. Relative to HTTP `deliver_at`, `sent_at` ran +6 to +251 ms late, `ts` was about 10–12 ms after `sent_at`, and client receipt ranged −27 to +232 ms. [Live runner](../tests/realtime/run.mjs) [WebSocket driver](../tests/realtime/ws-driver.mjs)

Two sockets attached to the same channel through two reopen grants both received the identical frame sequence with identical `evt_` ids and identical `message_id`s. [Live runner](../tests/realtime/run.mjs)

A pre-expiry socket remained open after expiry. A connection attempted about 2.1–2.2 seconds after expiry completed the upgrade, then immediately closed with code `4000` and empty reason; a garbage `token` value behaves identically (upgrade, then 4000, empty reason). Reopening issued a fresh grant that attached to the same channel. [Live runner](../tests/realtime/run.mjs)

## Social Memory

`ingest` preserved a three-message ordered transcript and returned exactly `{ingested:3}`; `ingested` equals the transcript length. Ingest without an `Idempotency-Key` returns 200 `{ingested:n}`. An empty transcript returns 422 `too_short` at `["transcript"]`. Same-body replay with the same `Idempotency-Key` returned the same 200 body. The same key with a different body also returned 200 and replayed `{ingested:3}`, not 409; the specification now states this first-write-wins rule. [Live runner](../tests/realtime/run.mjs)

Fresh-scope recall returned exactly `{context:""}`. After ingest, recall for Xena surfaced a code Yara stated about Xena and attributed it to Xena. `ask` returned that code; an ordering question returned blue-first and green-second. Assertions target these semantic invariants, not prose. Empty `ask.question` returned 422 with `loc:["question"]`, type `string_too_short`. [Live runner](../tests/realtime/run.mjs)

## Specification contradictions resolved by live testing

- `attached` is `{type,channel,server_time}`, not `{id,type,channel,ts,data}`. [Live runner](../tests/realtime/run.mjs)
- Expired and garbage grants upgrade and close with code 4000. [Live runner](../tests/realtime/run.mjs)
- WSS `message_id` differs from scheduled HTTP `id`. [Live runner](../tests/realtime/run.mjs)
- Same idempotency key plus different ingest body replayed 200, not 409. [Live runner](../tests/realtime/run.mjs)
- `record_event` emitted no signal frame in the attached test. [Live runner](../tests/realtime/run.mjs)
- `max_typing_ms` excludes the fixed 200 ms bubble gap, and typing has a 500 ms floor. [Live runner](../tests/realtime/run.mjs)
- Idempotency is keyed by `(owner,key)`, not per scope. [Live runner](../tests/realtime/run.mjs)

## Targeted closure experiments

### Signal frames: definitive negative

A fresh thread was opened with `integrations.social_signals.scope_id` set. The suite recorded `message_edited` before WSS attachment, then `typing_start`, `typing_stop`, and `message_edited` from multiple senders after attachment. It also submitted a modeled two-human batch while attached. Every event response and the submit response had `tags:[]`; no `turn_taking.signal` frame arrived before, during, or after the delivered reply. [Live runner](../tests/realtime/run.mjs)

The Hermes client's receive loop has explicit branches only for `turn_taking.message` and `turn_taking.typing`; it neither expects nor handles `turn_taking.signal`. Repository search found no signal-frame implementation elsewhere in the plugin. [Hermes WebSocket client](../sources/hermes-humalike-plugin/turn_taking/service.py)

This is a definitive negative across the requested integration, attachment-timing, event-type, sender, and submit-tag hypotheses. Production may have another undocumented trigger, but the documented inputs did not expose it. [Live runner](../tests/realtime/run.mjs)

### `stay_silent`: resolved

The modeled batch on the Social Signals thread contained two humans clearly addressing one another, with a lurker system prompt. Production returned exactly `{decision:"stay_silent",turn_epoch:1,tags:[],recalled_context:""}` in all three current runs; the suite asserts that exact body whenever the decision occurs without requiring the nondeterministic choice on every run. Five additional engineered lurker cases on the memory-integrated thread (named human-to-human dialogue, `@someone-else`, a bare `ok thanks`, an explicitly private exchange) all returned `speak`. [Live runner](../tests/realtime/run.mjs)

### Multi-bubble WSS metadata: resolved

A forced five-thought reply produced five scheduled entries and five WSS message frames in the reference run; the suite asserts 2–5. Every frame echoed the nested metadata object unchanged, positions were `0,1,2,3,4`, and both scheduled and delivered arrays remained ordered. All delivered `message_id` UUIDs differed from their position-matched scheduled HTTP `id` values. [Live runner](../tests/realtime/run.mjs) [WebSocket driver](../tests/realtime/ws-driver.mjs)

### Idempotency storage semantics: resolved

On a fresh scope, key K first ingested `Xavier works at Acme-693083`. Replaying K with the same body and then with changed body `Xavier works at Globex-693083` returned the original 200 `{ingested:1}` response both times. Recall and ask subsequently returned Acme and omitted Globex, with the Acme token present exactly once. Reusing K on a **different** `scope_id` with a two-message body also replayed `{ingested:1}` and stored nothing: recall on the second scope returned `{context:""}`. The observed rule is **first body wins, indexed by `(owner,key)` regardless of scope or body hash**. [Live runner](../tests/realtime/run.mjs)

## Remaining unknowns

Only the production trigger for `turn_taking.signal` remains unknown after the definitive negative matrix above. Grant behavior is proven for the ~2-second post-expiry window and for garbage tokens, not for every late-connect interval. Whether an idempotency key is also shared across routes (`ingest` is the only route that accepts one) was not probed. [Live runner](../tests/realtime/run.mjs)