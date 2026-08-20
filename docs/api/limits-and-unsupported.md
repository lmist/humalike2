# Limits and unsupported behavior

This page separates tested contract from behavior that is intentionally not a
public promise. Do not build product guarantees on the items below.

## Explicitly unresolved

| Area | Current boundary |
| --- | --- |
| Analyze report linkage | `analyze` returns a complete report but no report id, `Location`, or `x-report-id`. `Report/by-id` exists, yet the tested action flow cannot address the new report. |
| Social Signals | Documented triggers produce `tags:[]` and no `turn_taking.signal` frames. The `SignalData` wire contract is intentionally undefined; another undocumented trigger may exist. |
| Cross-tenant behavior | Valid absent repository ids return `200 null`, but one bearer key cannot prove the behavior for another owner's existing resource. Do not infer cross-tenant guarantees from absence tests alone. |
| Exact 429 behavior | No stress test established quotas. Exact status body, quota policy, and rate headers are unresolved. |
| Failure payload categories | No persona job or audit reached `status:"failed"` in the reference runs. A non-null job `error`, including the documented `"provider_error"` category, is a documented default rather than live-proven behavior. |

## Other non-promises

- Grant close code `4000` is proven for a garbage token and an attempt about
  two seconds after expiry, not for every possible late-connect boundary.
- Model policy, strategy tie-breaking, response wording, bubble split
  heuristics within the 1–5 bound, and channel inference for channel-less
  learning transcripts are not deterministic contracts.
- Retention, deletion, residency, provider/model versions, prompt versions,
  production encryption details, and device-authorization support are not
  public behavioral contracts.
- The component prices in the recreation are configuration values. Observed
  credit totals are useful for planning conformance runs, not guaranteed
  public prices.

## Unsupported public operations

The public API does not document list, clear, or delete routes for threads,
memory scopes, messages, or facts. Social Memory reset means choosing a new
`scope_id`. Do not rely on an undocumented route.

The plugin's privileged device-authorization routes are outside the tested
customer API and are not part of this recreation.

## What is tested instead

The authoritative acceptance evidence is the two committed suites:

```sh
export HUMALIKE_API_KEY=ak_...
export HUMALIKE_API_URL=http://localhost:8080
./tests/realtime/run.sh
./tests/intelligence/run.sh
```

They assert exact field names, status literals, error casing and messages,
limits, owner-safe absence, idempotency, epochs, pacing, WebSocket frames,
job phases, evaluation gates, and billing invariants. New production behavior
should become a live assertion before it becomes a normative documentation
promise.
