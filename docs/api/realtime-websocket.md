# Realtime WebSocket

Realtime delivery is attached to a turn-taking thread. Obtain a fresh grant
from `open_thread`, then connect to its `realtime.connect_url`.

## Connect flow

1. Authenticate an HTTP `open_thread` request with a bearer key.
2. Read `realtime.connect_url` and `channel` from the response.
3. Open the URL as a WebSocket. Do not add another bearer header.
4. Wait for the unwrapped `attached` frame.
5. Submit inbound messages and call `respond` over HTTP.
6. Consume the scheduled reply frames on the socket.
7. Reopen the same thread for a new grant after disconnect or expiry.

The URL has exactly this shape:

```text
wss://<origin-host>/v1/ws/turn-taking-thread?token=<payload>.<signature>
```

The token is two base64url segments, `payload.signature`; the signature is a
43-character HMAC-SHA256-sized segment. Its TTL is 30 seconds. Treat the
entire URL as a secret.

Example with `wscat`:

```sh
wscat -c 'wss://HOST/v1/ws/turn-taking-thread?token=PAYLOAD.SIGNATURE'
```

The first frame is not an event envelope:

```ts
type AttachedFrame = {
  type: "attached";
  channel: string;
  server_time: string; // YYYY-MM-DDTHH:MM:SS.ffffff+00:00
};
```

`server_time` is the only timestamp using the `+00:00` offset form. HTTP and
event timestamps use literal `Z`:
`YYYY-MM-DDTHH:MM:SS.ffffffZ`.

## Event envelope

Every frame after `attached` has:

```ts
type EventFrame<T> = {
  id: string;       // evt_ followed by 32 lowercase hex characters
  type: string;
  channel: string;
  ts: string;       // microsecond UTC Z timestamp
  data: T;
};

type TypingData = {thread_id: string; typing: boolean};

type MessageData = {
  message_id: string;
  thread_id: string;
  content: string;
  position: number;
  sent_at: string;
  metadata: Record<string, unknown> | null;
};
```

The tested frame types are:

```ts
type TypingFrame = EventFrame<TypingData> & {
  type: "turn_taking.typing";
};
type MessageFrame = EventFrame<MessageData> & {
  type: "turn_taking.message";
};
```

## Reply sequence

For `N` scheduled entries, the sequence is exactly `N + 3` frames:

```text
attached
turn_taking.typing {thread_id, typing:true}
turn_taking.message  // one per scheduled entry, position order
...                  // N message frames
turn_taking.typing {thread_id, typing:false}
```

No other frame is inserted under the documented flow. Every frame uses the
thread's `channel`. Message `position` is zero-based. `message_id` is a UUID
generated for delivery and is intentionally different from the matching HTTP
`scheduled[].id`; do not use one in place of the other.

The complete `respond.metadata` value is echoed in every message frame.
When `metadata` was omitted from `respond`, every frame carries
`"metadata":null`.

## Expiry and invalid grants

An already attached socket survives grant expiry and can continue to receive
frames. Expiry is checked for late connection attempts, not as a forced
disconnect of attached sockets.

A connection attempted after an expired grant, or with a garbage token,
completes the HTTP upgrade and then closes with:

```text
code: 4000
reason: ""
```

The conformance observation is about two seconds after expiry; behavior at
every exact boundary is not a separate contract.

## Reconnection and multiple sockets

Call `open_thread` with the existing `thread_id` to rotate the grant and
reconnect:

```sh
curl -sS "$HUMALIKE_API_URL/v1/turn-taking/actions/open_thread" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"THREAD_UUID"}'
```

The new connection starts with a fresh `attached` frame on the same channel.
Multiple sockets attached to the same owner-scoped thread through different
grants receive identical frames, including identical event ids and delivery
message ids.

No `turn_taking.signal` frame was observed for the documented Social Signals
events and batches. No SignalData wire contract is defined.
