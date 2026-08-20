# Turn-taking

All turn-taking routes require bearer authentication. Thread state is scoped
to the authenticated owner.

## `POST /v1/turn-taking/actions/whoami`

The request body is `{}`. The response has exactly one non-empty field:

```ts
type WhoamiResponse = {user_id: string};
```

```sh
curl -sS "$HUMALIKE_API_URL/v1/turn-taking/actions/whoami" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" -d '{}'
```

## `POST /v1/turn-taking/actions/open_thread`

```ts
type OpenThreadRequest = {
  thread_id?: string;
  integrations?: {
    social_signals?: {scope_id?: string; channel_id?: string};
    social_memory?: {memory_bank_id: string};
  };
};

type OpenThreadResponse = {
  thread: {
    id: string;
    user_id: string;
    created_at: string;
    updated_at: string;
  };
  channel: string;
  realtime: {connect_url: string; expires_at: string};
};
```

Omitting `thread_id` creates a UUID. Supplying an unused UUID creates that
thread. `channel` is exactly `turn-taking-thread/{thread.id}`.

`social_signals` accepts an optional `scope_id` or `channel_id`.
`social_memory.memory_bank_id` selects the memory bank used by later
submissions. Reopening the same owner-scoped thread preserves its id and
`created_at`, strictly advances `updated_at`, rotates the grant, and issues a
later `expires_at`. Supplying a new memory bank replaces the selection;
omitting `integrations` on a later reopen preserves it.

The grant URL is:

```text
wss://<origin-host>/v1/ws/turn-taking-thread?token=<payload>.<signature>
```

There is exactly one `token` query parameter. The two segments are base64url;
the signature is 43 characters. The grant expires 30 seconds after issuance
(the conformance window is 25–35 seconds). See
[Realtime WebSocket](realtime-websocket.md).

```sh
curl -sS "$HUMALIKE_API_URL/v1/turn-taking/actions/open_thread" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"integrations":{"social_memory":{"memory_bank_id":"conversation-42"}}}'
```

## `POST /v1/turn-taking/actions/submit_messages`

```ts
type InboundMessage = {
  sender: string;
  content: string;
  client_ts?: string;
  has_media?: boolean;
};

type SubmitMessagesRequest = {
  thread_id: string;
  messages: InboundMessage[];
  system_prompt?: string;
  skip_decide?: boolean;
};

type SubmitMessagesResponse = {
  decision: "speak" | "stay_silent";
  turn_epoch: number;
  tags: string[];
  recalled_context: string;
};
```

### Limits

| Value | Accepted range |
| --- | --- |
| `messages` | 1–20 entries |
| `sender` | 1–255 characters |
| `content` | 1–4000 characters |

The lower/upper violations use request-validation details such as `too_short`,
`too_long`, or `string_too_long`. The first accepted batch on a fresh thread
has `turn_epoch: 1`; each later accepted batch increments it by exactly one.
`record_event` does not increment the epoch.

`skip_decide:true` returns `decision:"speak"` without a modeled decision.
Any inbound message with `has_media:true` does the same. Both paths still
record the batch, increment the epoch, and can populate `recalled_context`
from the thread's configured Social Memory bank. An empty integration returns
`recalled_context:""`.

For the documented Social Signals triggers, `tags` is `[]` and no signal
frames are emitted. This is the tested behavior; no `SignalData` wire shape
is promised.

```sh
curl -sS "$HUMALIKE_API_URL/v1/turn-taking/actions/submit_messages" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id":"THREAD_UUID",
    "messages":[{"sender":"Human","content":"Can you help with this?","has_media":false}],
    "skip_decide":true
  }'
```

## `POST /v1/turn-taking/actions/record_event`

```ts
type RecordEventRequest = {
  thread_id: string;
  type: "typing_start" | "typing_stop" | "message_edited";
  sender: string;
  client_ts?: string;
};
type RecordEventResponse = {tags: string[]};
```

Each documented event returns exactly `{tags:[]}`. Events are free and do not
advance `turn_epoch`. An unknown event type is HTTP 422 with a `literal_error`
detail at `loc:["type"]`.

```sh
curl -sS "$HUMALIKE_API_URL/v1/turn-taking/actions/record_event" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"THREAD_UUID","type":"typing_start","sender":"Human"}'
```

## `POST /v1/turn-taking/actions/respond`

```ts
type RespondRequest = {
  thread_id: string;
  content: string;
  turn_epoch: number;
  system_prompt?: string;
  agent_name?: string;
  pacing?: {
    reading_delay_ms?: number;
    typing_wpm?: number;
    max_typing_ms?: number;
  };
  metadata?: Record<string, unknown>;
};

type ScheduledMessage = {
  id: string;
  thread_id: string;
  content: string;
  position: number;
  deliver_at: string;
  status: "scheduled";
  created_at: string;
  updated_at: string;
};

type RespondResponse = {
  scheduled: ScheduledMessage[];
  superseded: boolean;
};
```

A current epoch produces 1–5 scheduled bubbles. A draft that would produce
more than five natural bubbles is merged down to at most five without
truncating content. The service may rewrite the draft; clients should use
the returned `content`.

For bubble `i`, let `words_i` be its whitespace-token count. The exact pacing
formula is:

```text
typing_i  = min(max_typing_ms, max(500, words_i / typing_wpm * 60000))
deliver_0 = created_at_0 + reading_delay_ms + typing_0
deliver_i = deliver_(i-1) + 200 + typing_i   (i >= 1)
```

The 500 ms floor applies before the cap. The fixed 200 ms inter-bubble gap is
outside `max_typing_ms`. Omitted `pacing` members default to:

| Member | Default |
| --- | ---: |
| `reading_delay_ms` | 0 |
| `typing_wpm` | 150 |
| `max_typing_ms` | 8000 |

`metadata` is opaque and is deeply echoed on every delivered bubble. If it is
omitted, the WebSocket `metadata` value is `null`.

If the submitted epoch is stale, the response is HTTP 200 and exactly:

```json
{"scheduled":[],"superseded":true}
```

The stale path schedules no messages and adds no `turn-taking` or
`theoryofmind` charge.

```sh
curl -sS "$HUMALIKE_API_URL/v1/turn-taking/actions/respond" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id":"THREAD_UUID",
    "turn_epoch":1,
    "content":"First bubble.\n\nSecond bubble.",
    "agent_name":"Assistant",
    "pacing":{"reading_delay_ms":0,"typing_wpm":150,"max_typing_ms":8000},
    "metadata":{"request_id":"client-42"}
  }'
```
