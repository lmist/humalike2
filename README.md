# Humalike API recreation

This repository contains the clean-room Humalike API contract, a local FastAPI
recreation, and live conformance suites that exercise the public behavior.

## Repository map

| Path | Contents |
| --- | --- |
| `spec/` | Normative protocol, API, domain, and parity specifications |
| `service/` | FastAPI recreation (`service/humalike/`) |
| `tests/` | Realtime/memory and intelligence/persona conformance suites |
| `docs/` | End-user and project documentation |
| `clients/` | Client integrations and contract consumers |
| `examples/` | Runnable request examples |

## Start here

See [`docs/api/README.md`](docs/api/README.md) for the product overview,
quickstart, endpoint index, authentication, local deployment, and links to
each API area.

## Run conformance locally

Start the recreation, seed a test key, and point both suites at it:

```sh
export HUMALIKE_API_KEY=ak_...
export HUMALIKE_API_URL=http://localhost:8080
./tests/realtime/run.sh
./tests/intelligence/run.sh
```

The intelligence suite is asynchronous and may take substantially longer than
the realtime suite. Run sequentially when comparing billing deltas.

**Status:** `tests/realtime/run.mjs` and `tests/intelligence/run.mjs` together
are the acceptance gate; a release candidate requires both suites to pass with
zero failed assertions and zero skips.
