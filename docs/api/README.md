# Humalike API

The Humalike API recreation exposes a small set of composable capabilities:

- turn decisions and paced, realtime delivery for group-chat agents;
- social memory for ordered transcripts, subject facts, recall, and grounded
  answers;
- social learning for extracting reusable communication style;
- Theory of Mind for predicting reception before sending a reply;
- observability reports and progressive conversation audits;
- persona population generation, enhancement, and validation; and
- usage accounting, component credits, and owner-scoped auditability.

The public surface is deliberately narrow. Resources are isolated by the
owner derived from the bearer key. Memory is append-only, thread epochs make
stale replies safe to discard, and asynchronous persona resources are polled
through owner-scoped repository reads.

## Documentation map

| Guide | Covers |
| --- | --- |
| [Authentication](authentication.md) | Bearer credentials and transport invariants |
| [Errors and billing](errors-and-billing.md) | Error envelopes, documented defaults, credits, and usage |
| [Turn-taking](turn-taking.md) | HTTP decisions, threads, events, and reply scheduling |
| [Realtime WebSocket](realtime-websocket.md) | Grants, frames, delivery, expiry, and reconnect |
| [Social Memory](social-memory.md) | Ingest, idempotency, recall, and ask |
| [Social Learning](social-learning.md) | Learning profiles and prompt blocks |
| [Theory of Mind](theory-of-mind.md) | Reaction forecasting and reply refinement |
| [Observability](observability.md) | Reports and full audits |
| [Personas](personas.md) | Population, enhancement, and evaluation jobs |
| [Limits and unsupported behavior](limits-and-unsupported.md) | Explicit open questions and non-promises |

## Quickstart

### Use a deployed service

Set the base URL and bearer key. The production default base URL is
`https://api.humalike.com`.

```sh
export HUMALIKE_API_URL=https://api.humalike.com
export HUMALIKE_API_KEY=ak_...
curl -sS "$HUMALIKE_API_URL/v1/turn-taking/actions/whoami" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Success is exactly:

```json
{"user_id":"..."}
```

Every public route requires `Authorization: Bearer <token>`. Do not put keys
in source control, URLs, shell history, logs, or client-visible telemetry.
See [Authentication](authentication.md).

### Run the recreation locally

The service uses SQLite by default and creates its tables at startup. From the
repository root:

```sh
export HUMALIKE_DATABASE_URL=sqlite:///./humalike.db
export HUMALIKE_SECRET='replace-this-development-secret'
export HUMALIKE_SEED_KEYS=''
export HUMALIKE_PORT=8080
```

`HUMALIKE_DATABASE_URL` may be a SQLAlchemy PostgreSQL URL when a PostgreSQL
deployment is desired. `HUMALIKE_SECRET` signs WebSocket grants and hashes API
keys; override the development default. `HUMALIKE_SEED_KEYS` is a
comma-separated list of plaintext keys registered at boot. `HUMALIKE_PORT`
sets the HTTP port; the host defaults to `127.0.0.1`.

Install the service and development dependencies, then run either:

```sh
python -m pip install -e 'service[dev]'
PYTHONPATH=service uvicorn humalike.app:app --host 127.0.0.1 --port "$HUMALIKE_PORT"
# or
PYTHONPATH=service python -m humalike.main
```

In a second shell, mint a funded development key through the operator utility:

```sh
export HUMALIKE_API_KEY="$(
  PYTHONPATH=service python -c \
    'from humalike.auth import mint_key; print(mint_key())'
)"
export HUMALIKE_API_URL=http://127.0.0.1:8080
curl -sS "$HUMALIKE_API_URL/v1/turn-taking/actions/whoami" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'
```

The recreation also supports seeding a known key before startup:

```sh
export HUMALIKE_SEED_KEYS=ak_local_development_key
```

Keep that value private even in local logs. A key is associated with an
owner; clients never submit an owner id.

## Common transport rules

Bodies are UTF-8 JSON. Actions and projections use `POST`; repository reads
use `GET`. Successful and error responses are JSON and carry a non-empty
`x-request-id`. Sampled responses do not carry rate-limit or `Retry-After`
headers. Timestamps are normally
`YYYY-MM-DDTHH:MM:SS.ffffffZ`; the attached WebSocket frame uses
`YYYY-MM-DDTHH:MM:SS.ffffff+00:00`.

The examples use `$HUMALIKE_API_URL` and `$HUMALIKE_API_KEY`:

```sh
curl -sS "$HUMALIKE_API_URL/<path>" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '<json>'
```

Unknown request fields are ignored by the tested routes. Clients should still
send only fields in the documented request types.
