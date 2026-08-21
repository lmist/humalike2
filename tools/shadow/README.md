# Shadow proxy — golden dataset from the live plugin

`shadow_proxy.py` sits between a client (the Hermes plugin) and two Humalike
backends. The client's contract is untouched: it points `HUMALIKE_API_URL` at
the proxy and gets the **recreation's** answers back. Every request is also
mirrored, in arrival order, to **production** with the production key, and
both sides are written to a JSONL dataset.

```
Hermes plugin ──HTTP/WS──▶ shadow proxy :8081 ──▶ recreation :8080   (answers go back)
                                │
                                └──▶ api.humalike.com                  (recorded only)
```

## Run

```sh
# recreation on :8080 first (service/), then:
tools/shadow/run.sh            # prod key read from <repo>/.env HUMALIKE_API_KEY
tools/shadow/run.sh --no-mirror

# point the plugin at it (~/.hermes/.env) and restart the gateway
HUMALIKE_API_URL=http://127.0.0.1:8081
HUMALIKE_API_KEY=ak_local_development_key     # the recreation's seeded key

curl -s localhost:8081/internal/shadow/status | jq
tools/shadow/report.py         # summarize the newest dataset
```

Dataset: `tools/shadow/golden/<UTC date>.jsonl` (gitignored — it holds chat
transcripts; copy out deliberately).

## What is recorded

One line per HTTP exchange (`kind: http`): request (method, path, query,
body), `local` and `prod` responses (status, `x-request-id`, body, latency),
the id/epoch rewrites applied to the mirror, and a `diff` (`status`,
`decision`, `turn_epoch`, `scheduled_count`, `scheduled_contents`,
`error_code`, key-set differences, and the `diverged` flag list).

One line per WebSocket frame (`kind: ws`, `side: local|prod`) with
`recv_offset_ms` from socket open, so bubble pacing can be compared; plus
`ws_event` lines for open/close (close codes included).

Never recorded: `Authorization`, keys, grant tokens (`token=[REDACTED]`).

## How the mirror stays coherent

* Ids: after each pair of responses the proxy walks both JSON bodies in
  parallel; wherever the same path holds two different UUIDs it learns
  `local → prod`. Later requests have every known local UUID rewritten in
  path, query and body (thread ids, persona job ids, report ids).
* Epochs: from each paired `submit_messages` it learns `(thread, local
  epoch) → prod epoch`; `respond` is re-stamped with the prod epoch.
* Ordering: mirror calls run on one FIFO worker, so a `submit` never reaches
  production before the `open_thread` that created its thread.
* Realtime: the client's socket is bridged to the recreation (frames
  recorded in flight); production's grant is opened by the proxy itself
  within its 30 s TTL and its frames are recorded alongside.

## Cost

Mirroring spends production credits at production prices — turn-taking and
social-memory are cheap, Theory-of-Mind `respond` is 4, `social-learning`
extract 15, personas `enhance` 85. To exclude a family:
`SHADOW_SKIP_PATHS=/internal/,/v1/personas,/v1/social-learning`.
