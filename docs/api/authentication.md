# Authentication

## Bearer scheme

Every public HTTP route requires:

```http
Authorization: Bearer <api-key>
```

Use the same key for HTTP requests and to obtain a WebSocket grant through
`open_thread`. The WebSocket connection itself uses the returned grant URL;
it does not require an additional bearer header.

Missing authorization, a malformed scheme, a bare `Bearer`, and an invalid
`ak_` value all return HTTP 401 with this exact body:

```json
{"error":{"code":"UNAUTHORIZED","message":"missing or invalid credentials"}}
```

The outer object has no other keys. The response is JSON and carries a
non-empty `x-request-id`.

## Key handling

Treat an API key as a secret:

- keep it in a secret manager or environment variable;
- do not commit it, print it, put it in a URL, or include it in request logs;
- send it only in the `Authorization` header;
- rotate it if it appears in a trace, issue, build log, or client bundle; and
- use separate keys for local development and conformance runs.

The recreation stores an HMAC lookup value rather than the plaintext key and
derives an owner principal during authentication. Callers never send an owner
id. Owner predicates apply to threads, memory scopes, jobs, reports, audit
runs, and usage.

For local development, seed plaintext keys with `HUMALIKE_SEED_KEYS` or mint
one with the operator utility:

```sh
PYTHONPATH=service python -c \
  'from humalike.auth import mint_key; print(mint_key())'
```

The printed value is the only time the plaintext minted key is returned.
Store it in `HUMALIKE_API_KEY` without echoing it in diagnostics.

## No rate headers

The conformance suites observed no rate-limit or `Retry-After` headers,
including on errors. Clients must not depend on such headers being present.
Exact 429 status, quota, body, and header behavior is unresolved; see
[Limits and unsupported behavior](limits-and-unsupported.md).
