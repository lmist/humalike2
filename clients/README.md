# Typed clients

Two hand-written clients over the same contract:

| Path | What it is |
| --- | --- |
| `clients/typescript/humalike.d.ts` | Request/response types for every endpoint in spec/03 and spec/04. No runtime code. |
| `clients/typescript/client.mjs` | ESM fetch wrapper, one method per endpoint, bearer auth, `x-request-id` capture. Runs under `node` with no build step; type-checks under `tsc --checkJs`. |
| `clients/python/humalike_client.py` | `TypedDict`-typed client with the same coverage, standard library `urllib` only. |

Both read `HUMALIKE_API_URL` (default `https://api.humalike.com`) and
`HUMALIKE_API_KEY`, the same variables the conformance suites use, so a client,
an example, and a suite run can share one environment.

```js
import { HumalikeClient } from './clients/typescript/client.mjs';
const hum = new HumalikeClient();
const { user_id } = await hum.whoami();
```

```py
from humalike_client import HumalikeClient
hum = HumalikeClient()
print(hum.whoami()["user_id"])
```

The types are transcribed from the spec, which is transcribed from live
assertions. Keeping them synchronized with the specification is a release gate
(spec/08 §Release gates), so a spec change is expected to arrive with a change
here in the same commit.

## Phase map

Section headers in all three files carry these phase markers, so a phase's
client surface can be reviewed without reading the whole file.

| Phase (spec/07) | Endpoints | TypeScript types | `client.mjs` | `humalike_client.py` |
| --- | --- | --- | --- | --- |
| 1 — Identity, tenancy, credits | `POST /v1/turn-taking/actions/whoami`, `POST /v1/credits/projections/usage-summary` | `WhoamiResponse`, `UsageSummary`, `ComponentSlug`, `DayName` | `whoami`, `usageSummary` | `whoami`, `usage_summary` |
| 2 — Thread state and realtime delivery | `POST /v1/turn-taking/actions/open_thread`, `WS /v1/ws/turn-taking-thread` | `OpenThreadRequest/Response`, `ThreadIntegrations`, `AttachedFrame`, `EventFrame`, `TypingFrame`, `MessageFrame`, `GrantCloseCode` | `openThread`, `grantUrl` | `open_thread`, `grant_url_parts` |
| 3 — Model-backed turn-taking | `submit_messages`, `record_event`, `respond` | `SubmitRequest/Response`, `RecordEventRequest/Response`, `RespondRequest/Response`, `Pacing`, `ScheduledMessage` | `submitMessages`, `recordEvent`, `respond` | `submit_messages`, `record_event`, `respond` |
| 4 — Social Memory | `ingest`, `recall`, `ask` | `IngestRequest/Response`, `RecallRequest/Response`, `AskRequest/Response`, `MemoryMessage` | `ingest` (owner-wide `Idempotency-Key`), `recall`, `ask` | `ingest`, `recall`, `ask` |
| 5 — Social Learning and foresee | `POST /v1/social-learning/actions/extract`, `POST /v1/foresee/actions/foresee` | `LearningProfile`, `ExtractRequest/Response`, `ForeseeRequest/Response`, `MentalState`, `PredictedReaction` | `extract`, `foresee` | `extract`, `foresee` |
| 6 — Observability and audit | `analyze`, `Report/by-id`, `audit_prepare`, `audit_launch`, `audit-run` | `Report`, `Interaction`, `PerUser`, `Finding`, `AuditPrepareResponse`, `AuditLaunchResponse`, `AuditProjection` | `analyze`, `reportById`, `auditPrepare`, `auditLaunch`, `auditRun`, `waitForAudit` | `analyze`, `report_by_id`, `audit_prepare`, `audit_launch`, `audit_run`, `wait_for_audit` |
| 7 — Personas | `generate`, `Population/by-id`, `enhance`, `Enhancement/by-id`, `validate`, `Evaluation/by-id` | `Blueprint`, `FieldSpec`, `Persona`, `PopulationResource`, `EnhancementResource`, `EvaluationResource`, `Gate`, `Diversity`, `Marginal` | `generatePersonas`, `population`, `enhancePersona`, `enhancement`, `validatePersonas`, `evaluation`, `waitForJob` | `generate_personas`, `population`, `enhance_persona`, `enhancement`, `validate_personas`, `evaluation`, `wait_for_job` |

Phases 0 and 8 add no client surface: phase 0 is the live-suite harness and
phase 8 is hardening. Both act on the clients only through the protocol
behaviors below.

## Contract details the clients encode

These are the places where a naive client would be wrong, so they are handled
in code rather than left to the caller:

- **Errors carry a code, not a message.** `HumalikeApiError.code` exposes
  `error.code`; branch on it. Message text is not a stable contract, and the
  402/403/502 bodies are documented defaults that were never exercised live
  (spec/02 §Billing).
- **`x-request-id` is captured from every response**, including 401 and 422.
  Production sets it on every captured response, and it is the only correlator
  a caller has.
- **A superseded respond is a success.** `{"scheduled": [], "superseded": true}`
  arrives as HTTP 200 and is not billed, so it must not be treated as an error.
- **A missing repository id is a success.** `Report`, `Population`,
  `Enhancement`, and `Evaluation` return HTTP 200 with JSON `null` for a valid
  unknown UUID; only a *malformed* id is a 400.
- **`Idempotency-Key` is owner-wide, not per scope.** The same key with a
  changed body or a different `scope_id` replays the first response and stores
  nothing new.
- **`analyze` returns no identifier.** There is deliberately no `id`,
  `Location`, or `x-report-id`, so the client offers no "read my report back"
  helper. Adding one would invent surface (spec/08 open question 1).
- **Audit completion is inferred, not reported.** The projection never exposes
  `status` or `stage`; `waitForAudit`/`wait_for_audit` poll until
  `replies.length === verdicts.length` and the projection is stable across two
  polls.
- **Long default timeouts.** Population and enhancement ran about 52 s and 37 s
  live, so both clients default to a 300 s request timeout rather than a
  socket-default few seconds.
- **`tags` is always `[]`.** No documented Social Signals trigger produced a
  tag or a frame, so the types promise no `SignalData` payload
  (spec/08 open question 2).
