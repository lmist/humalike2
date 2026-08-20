---
title: Hermes Humalike Plugin Analysis
description: Analysis of how the Hermes plugin calls and operationalizes Humalike APIs.
tags:
  - humalike
  - research
  - plugin
  - hermes
status: complete
---
# Hermes Humalike plugin analysis

## Configuration and authentication

The plugin defaults `HUMALIKE_API_URL` to `https://api.humalike.com`, strips a trailing slash, and reads `HUMALIKE_API_KEY` fresh per call. Every normal request sends `Authorization: Bearer <key>` and JSON content type. In multiplexed Hermes profiles, secret lookup fails closed rather than falling back to another profile's process environment. An empty URL explicitly disables calls; an empty key suppresses transcript egress instead of deliberately generating 401s. [Plugin source](../sources/hermes-humalike-plugin/source.md)

## Turn-taking integration

The transport calls exactly three core paths: `/v1/turn-taking/actions/open_thread`, `/submit_messages`, and `/respond`. `open_thread` can send a caller thread id and automatically enables Social Memory using a stable per-agent `memory_bank_id`. `submit_messages` sends `{thread_id,messages,system_prompt?}`. `respond` sends `{thread_id,content,turn_epoch,system_prompt?,metadata?,agent_name?,pacing}`. Default plugin pacing is 115 WPM; config can override reading delay, typing speed, and max typing delay per call. [Plugin source](../sources/hermes-humalike-plugin/source.md)

Inbound Hermes events are normalized to at most 20 messages. Sender is truncated to 255 characters, content to 4000, and captionless media becomes `[image]`, `[video]`, `[voice message]`, `[audio]`, `[document]`, `[sticker]`, or `[media]` with `has_media:true`. Mention annotation resolves platform ids before submission. System prompts are head-truncated to 100,000 characters. Metadata is used to carry forum-topic/reply state through delivered bubbles. [Plugin source](../sources/hermes-humalike-plugin/source.md)

The plugin reads the short-lived `realtime.connect_url` from open-thread, connects with no extra auth header, ignores the `attached` handshake, handles `turn_taking.message` and `turn_taking.typing`, and forwards message content plus echoed metadata to adapters. It does not implement reconnect inside the receive loop; a supervising task owns recovery. [Plugin source](../sources/hermes-humalike-plugin/source.md)

HTTP calls use a 30-second timeout. Missing config, transport errors, and HTTP failures return `None`, causing the gateway to behave as though turn-taking is off. Errors are logged and surfaced through notifications; a later success emits recovery and clears the alert. Non-JSON 2xx and internal parsing bugs intentionally propagate rather than being hidden. No plugin-side rate-limit parsing or `Retry-After` handling exists. [Plugin source](../sources/hermes-humalike-plugin/source.md)

## Social learning

Every fifth turn, a daemon refresh posts up to the latest 100 user-originated, per-speaker messages to `/v1/social-learning/actions/extract` as `{transcript:{messages:[{id,speaker,text}]}}`. A successful `prompt_block` is cached and injected into every subsequent agent prompt; it is also fed into turn-taking identity/voice. The default is one global last-writer-wins card, with optional per-session cards. Cache persists to JSON, failures are discarded, concurrent refresh per session is suppressed, and there is no time-based backoff. [Plugin source](../sources/hermes-humalike-plugin/source.md)

The plugin can optionally stop Hermes native memory from storing style and norms, leaving durable facts only. This prevents stale durable memory from competing with the live Social Learning voice card. [Plugin source](../sources/hermes-humalike-plugin/source.md)

## Persona enhancement

`/soul enhance` sends `{persona}` to `/v1/personas/actions/enhance`, then polls `/v1/personas/repositories/Enhancement/by-id/{id}` every two seconds for up to roughly five minutes. It maps 401, 402, 403, 429, 5xx, transport failure, missing result, provider failure, timeout, and malformed response into user-facing outcomes. The plugin adds an in-band “never use an em dash” directive, demonstrating that enhancement is prompt-driven and accepts only one persona text field in this version. [Plugin source](../sources/hermes-humalike-plugin/source.md)

## Device authorization

The plugin also reveals non-public/installer endpoints: `POST /v1/keys/actions/cli_create` with client/hostname/OS, and `POST /v1/keys/actions/cli_poll` with device code. The initial response includes device/user code, verification URI, expiry, and interval; poll states are pending, authorized, denied, expired; the authorized response exposes the `ak_…` key once. These routes use a separate gateway bearer credential and should not be treated as part of the ordinary customer API contract without explicit product authorization. [Plugin source](../sources/hermes-humalike-plugin/source.md)

## Integration conclusions

The plugin validates the documented base URL and bearer mechanism, proves request caps are enforced client-side, and shows expected fail-open behavior for chat availability. It adds important operational requirements absent from endpoint prose: profile-scoped secrets, transcript egress suppression when keyless, persisted voice cards, single refresh worker per session, notification/recovery state, and separation of durable facts from learned social style. [Plugin source](../sources/hermes-humalike-plugin/source.md)