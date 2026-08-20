# Unresolved behavior

Every behavior this recreation implements that production has **not** proven,
listed per phase. spec/07 §Delivery discipline requires each phase to ship an
explicit unresolved-behavior list, and spec/08 closes with the rule these
entries exist to honour: unknowns stay configuration, local safety
requirements, documented defaults, or explicitly unsupported behavior, and
must never be represented as established production behavior.

Every entry states three things:

- **Unknown** — what production has not shown us.
- **Recreation** — what this implementation does instead, and what kind of
  choice that is (documented default, deterministic substitute, local safety
  policy, or configuration).
- **Resolved by** — the evidence that would settle it. Per spec/08, a new
  discovery becomes a fresh live assertion first, then a research-digest
  update, and only then normative prose.

## Open-question index

| spec/08 question | Entries |
| --- | --- |
| 1. Analyze report linkage | [6.1](#61-analyze-exposes-no-report-identifier) |
| 2. Social Signals trigger | [2.2](#22-social-signals-trigger-and-payload) |
| 3. Tenant boundaries | [1.4](#14-cross-tenant-reads), [2.1](#21-cross-owner-thread-uuid) |
| 4. Credit exhaustion | [1.3](#13-402-body-reservation-release-and-replenishment) |
| 5. Authorization and throttling | [1.1](#11-403-body), [1.2](#12-429-quotas-and-rate-headers) |
| 6. Thread edge cases | [2.1](#21-cross-owner-thread-uuid) |
| 7. Grant boundary | [2.3](#23-grant-expiry-boundary-and-token-payload) |
| 8. Model policy | [3.1](#31-decision-model-and-prompts), [3.2](#32-bubble-split-policy-inside-the-1-5-bound), [4.2](#42-fact-extraction-and-contradiction-policy), [5.1](#51-metachannels-for-a-channel-less-transcript), [6.3](#63-agent_guess-heuristic), [7.2](#72-blueprint-design-policy) |
| 9. Failure payloads | [7.1](#71-failed-job-error-payload), [6.2](#62-stored-report-read-shape) |
| 10. Operational policy | [8.1](#81-retention-and-deletion), [8.2](#82-residency-and-encryption-at-rest), [8.3](#83-providermodelprompt-versions), [8.4](#84-device-authorization) |

---

## Phase 0 — Live contract harness

### 0.1 Intelligence assertion count

- **Unknown.** The intelligence suite completes a count that moves with poll
  counts and generated field counts; the latest confirming run passed 1,278,
  and roughly 1,280-1,360 is the stated range.
- **Recreation.** Release gates cite *the assertion set with zero failures and
  zero skips*, never a fixed number. A run that passes 1,278 and a run that
  passes 1,340 are both green.
- **Resolved by.** Nothing needs resolving; pinning a number would be the
  error. A suite change that makes the count deterministic would.

### 0.2 Exit code 3 as a budget signal

- **Unknown.** How production behaves *after* a 402 truncates a run — whether
  the remaining assertions would have passed — is unobservable from a depleted
  key.
- **Recreation.** Exit code 3 is reported as an environment/budget blocker and
  never reinterpreted as a product regression; a candidate is not accepted on a
  truncated run.
- **Resolved by.** A funded re-run reaching zero skips.

---

## Phase 1 — Identity, tenancy, and credits

### 1.1 403 body

- **Unknown.** Valid-but-forbidden authorization was never exercised. The 403
  body is documented, not live-proven.
- **Recreation.** Emits the documented default
  `{"error":{"code":"forbidden","message":"forbidden"}}` — note the lowercase
  code, which differs from the uppercase `UNAUTHORIZED` and `VALIDATION_ERROR`
  codes precisely because it comes from documentation rather than from capture.
  Clients branch on `error.code`, never on message text.
- **Resolved by.** A live 403 from a key that authenticates but lacks access to
  the addressed resource.

### 1.2 429, quotas, and rate headers

- **Unknown.** No rate-limit stress was authorized. No sampled response carried
  a rate-limit or `Retry-After` header, and no quota is established.
- **Recreation.** Enforces no throttling and emits no rate headers on any
  response. Internal limits, if a deployment adds them, MUST NOT invent
  production rate headers as part of compatibility.
- **Resolved by.** An authorized rate-limit test capturing the status, body,
  and headers of a throttled response.

### 1.3 402 body, reservation release, and replenishment

- **Unknown.** No reference run hit a 402, so the body, the exact point at
  which it is returned, reservation release on failure, replenishment timing,
  and recovery after funding are all unobserved.
- **Recreation.** Returns the documented default
  `{"error":{"code":"PAYMENT_REQUIRED","message":"insufficient credits"}}`
  before any billable work and without charge. Locally: `billing.reserve`
  checks balance minus outstanding reservations, `billing.release` frees a
  reservation when work fails, and `billing.reconcile_abandoned` releases
  reservations left behind by a crashed worker after 600 s. Replenishment has
  no API surface at all — balances move only through operator action.
- **Resolved by.** A deliberately depleted production key: the exact 402 body,
  whether a failed billable call leaves credits held, and how a top-up becomes
  visible.

### 1.4 Cross-tenant reads

- **Unknown.** One production key cannot prove another owner's data is
  unreachable. Nonexistent repository ids return `null`, but that is not the
  same evidence.
- **Recreation.** Every repository query and command applies the owner
  principal derived from the bearer; this is a **local safety requirement**,
  proven by `service/tests/test_billing_isolation.py`, not a production claim.
- **Resolved by.** Two funded production keys under an authorization that
  permits cross-account probing.

### 1.5 Component prices

- **Unknown.** Component prices observed during shared runs are informative,
  not stable public pricing.
- **Recreation.** Prices are configuration (`HUMALIKE_PRICE_*`), defaulting to
  the observed ratios. Only the six component *slugs* are treated as contract,
  because the suites key their billing assertions on them.
- **Resolved by.** A published price list, or per-component deltas from a
  dedicated key across enough runs to be stable.

### 1.6 What `daily_series.requests` counts

- **Unknown.** The seven-entry zero-filled UTC series is tested, but whether
  production counts every authenticated request, only billable calls, or
  something else is not pinned by any assertion.
- **Recreation.** Counts every authenticated request per UTC day, including
  free routes — so `total_calls` (captures) and `daily_series` (requests)
  legitimately disagree.
- **Resolved by.** A production run issuing a known mix of free and billable
  calls and comparing both projections.

---

## Phase 2 — Thread state and realtime delivery

### 2.1 Cross-owner thread UUID

- **Unknown.** Create-with-supplied-UUID and reopen are proven for the owning
  key. What production does when owner B supplies owner A's thread id — 403,
  404, a silent new thread, or a leak — is not.
- **Recreation.** Returns the documented-default 403 and never reads, mutates,
  or discloses the other owner's thread. Chosen as the **local safety policy**:
  of the plausible behaviors it is the only one that cannot leak existence *or*
  silently fork state.
- **Resolved by.** Two production keys and one shared UUID.

### 2.2 Social Signals trigger and payload

- **Unknown.** With the integration configured, before and after WSS
  attachment, across all documented event types and a two-human modeled batch,
  every response carried empty `tags` and no signal frame arrived. Another
  undocumented trigger may exist.
- **Recreation.** Accepts and stores the `social_signals` integration, returns
  `tags: []` everywhere, and emits no `turn_taking.signal` frame. The clients
  publish no `SignalData` type, so no caller can build on a shape that has
  never been observed.
- **Resolved by.** A production capture containing a non-empty `tags` array or
  a signal frame, with the trigger that produced it.

### 2.3 Grant expiry boundary and token payload

- **Unknown.** Close code 4000 is proven about two seconds after expiry and for
  garbage tokens — not for every late-connect interval, and not for the
  boundary itself. The token payload is opaque.
- **Recreation.** Validates the signature and a strict `exp`, completes the
  upgrade, then closes 4000 with an empty reason for anything invalid,
  regardless of how late. The payload carries owner, thread, channel, expiry,
  and a nonce; it is internal, and no client may parse it.
- **Resolved by.** Connect attempts sweeping the boundary (−100 ms, +100 ms,
  +1 s, +10 s) against production.

### 2.4 Delivery timing envelope

- **Unknown.** Observed `sent_at` trailed `deliver_at` by 6-251 ms and `ts`
  trailed `sent_at` by about 10 ms. Whether those are guarantees or artefacts
  of one deployment is unknown.
- **Recreation.** Stamps `sent_at` and `ts` at broadcast and aims to deliver
  inside that envelope; it treats the envelope as a **capacity target**, not a
  contract. The `docs/dashboards/realtime.json` lateness panel is the check.
- **Resolved by.** A latency distribution from production under load.

---

## Phase 3 — Model-backed turn-taking

### 3.1 Decision model and prompts

- **Unknown.** The decision prompts, model, strategy catalog, and tie-breaking
  behind `speak`/`stay_silent` are not public.
- **Recreation.** A **deterministic substitute**: a small scored strategy set
  (directly mentioned, keep silent, continue pending) in
  `humalike/engine/router.py`, capable of both outcomes, traced to
  `router_traces` with a `prompt_version`. The contract it must satisfy is the
  one the suites assert — `stay_silent` returns exactly
  `{decision:"stay_silent",turn_epoch,tags:[],recalled_context:""}` whenever it
  occurs — not a particular decision on a particular batch.
- **Resolved by.** Published prompts or model documentation; a suite that
  required a specific decision on a specific batch would contradict spec/08's
  assertion policy.

### 3.2 Bubble split policy inside the 1-5 bound

- **Unknown.** Production "may materially rewrite the draft"; the split
  heuristic within the 1-5 bound is model-driven and unspecified.
- **Recreation.** Splits on paragraph boundaries and merges the smallest
  adjacent pair until at most five bubbles remain, preserving every character —
  merge, never truncate. It does not rewrite the draft's wording at all, which
  is a strict subset of what production is allowed to do.
- **Resolved by.** A corpus of production drafts and their bubble splits.

### 3.3 Theory-of-Mind refinement on the reply path

- **Unknown.** `respond` bills `theoryofmind` alongside `turn-taking`, so a
  refinement stage exists, but its inputs, prompts, and effect on the emitted
  bubbles are not observable.
- **Recreation.** Runs a deterministic refinement stage and bills both
  components on the same non-stale path, matching the observed billing shape
  without claiming the production stage's behavior.
- **Resolved by.** A production capture that isolates the refinement's effect,
  or documentation of the stage.

---

## Phase 4 — Social Memory

### 4.1 Idempotency record lifetime

- **Unknown.** Replays are proven first-write-wins across identical bodies,
  changed bodies, and other scopes under an `(owner,key)` index. How long a key
  stays valid is not: no expiry was observed, and none is documented.
- **Recreation.** Keeps `idempotency_records` indefinitely, so a replay a year
  later still returns the first response. Chosen because the failure mode of
  forgetting (duplicated facts) is worse than the failure mode of remembering
  (storage).
- **Resolved by.** A replay of an old key against production.

### 4.2 Fact extraction and contradiction policy

- **Unknown.** Production's extraction model, its fact representation, and what
  it does when a later message contradicts an earlier one are not public. The
  tested behavior is external: recall and ask surface seeded tokens with
  correct attribution and order.
- **Recreation.** A **deterministic substitute**: subject-centric extraction
  with named-entity attribution falling back to the speaker, evidence links to
  the originating message, and contradictions recorded as a
  `contradicts_id` link rather than a delete — nothing is ever removed, so the
  original body is retained as the suites require.
- **Resolved by.** Production behavior on a deliberately contradictory
  transcript, checking whether the superseded fact survives recall.

### 4.3 Which memory routes bill

- **Unknown.** Live runs show `social-memory` charging 13 credits over 13 calls
  in a realtime pass, which constrains but does not uniquely determine which
  routes charge.
- **Recreation.** `ingest` is free; `recall` and `ask` each bill one
  `social-memory` unit. Configuration, matching the observed aggregate.
- **Resolved by.** Per-route usage deltas from a dedicated key.

---

## Phase 5 — Social Learning and foresee

### 5.1 `meta.channels` for a channel-less transcript

- **Unknown.** A transcript with explicit channels yields those channels plus
  `"unlabelled"`, but a channel-less transcript is **not stable**: both `[]`
  and `["general"]` were observed live.
- **Recreation.** Returns a deterministic value for the channel-less case. The
  clients and examples deliberately assert nothing about it, and neither
  should any caller.
- **Resolved by.** Enough production samples to show whether either value is
  reproducible — or confirmation that it is genuinely nondeterministic, which
  would make the current non-assertion permanent.

### 5.2 Profile storage separation

- **Unknown.** Keeping learned style separate from durable factual memory is a
  convention of the reference client, not a publicly tested API behavior.
- **Recreation.** Stores profiles in `learned_profiles`, never in
  `memory_facts`, and refreshes them independently. This is why the phase 5
  rollback is cheap: dropping profiles loses no facts.
- **Resolved by.** Documentation or an API that exposes the relationship
  between a learned profile and a memory scope.

### 5.3 foresee refinement quality

- **Unknown.** `refined_reply` and `refinement_rationale` are model-authored;
  no assertion pins their content beyond type and the subject-narrowing rule.
- **Recreation.** Produces a deterministic refinement satisfying the structural
  invariants: with `subject_name`, exactly one entry in each array named for
  the subject, and every emotion intensity in [0,1].
- **Resolved by.** Nothing available; per spec/08 generated prose is tested by
  schema, grounding, and invariants rather than exact wording.

---

## Phase 6 — Observability and audit

### 6.1 Analyze exposes no report identifier

- **Unknown.** `analyze` returns no `id`, no `Location`, and no `x-report-id`,
  so the report it stores is unreachable through the tested public flow. Whether
  production has a private linkage is unknown.
- **Recreation.** Stores the report owner-scoped and exposes **no** identifier
  from `analyze` — the absence is asserted on purpose, so adding an id would
  fail the gate. `Report/by-id` exists, stays owner-scoped, and returns `null`
  for a valid unknown UUID.
- **Resolved by.** A production route or field that links an analyze call to
  its stored report. Until then this stays an explicit unresolved linkage, not
  an actionable promise.

### 6.2 Stored Report read shape

- **Unknown.** Because of 6.1 no stored report was ever read back, so the read
  shape is documented only.
- **Recreation.** `Report/by-id` returns the same `Report` shape `analyze`
  returns.
- **Resolved by.** One successful production read of a stored report.

### 6.3 `agent_guess` heuristic

- **Unknown.** `agent_guess` is non-null in tested cases and, when non-null, is
  one of the participants; the heuristic behind it is not specified, and the
  conditions under which it is `null` are not established.
- **Recreation.** Uses a deterministic heuristic over the parsed transcript and
  always satisfies the tested constraint (null, or a participant).
- **Resolved by.** Production behavior on transcripts engineered to be
  ambiguous about which speaker is the agent.

### 6.4 The ~32,768-token budget

- **Unknown.** The audit enforces a token budget of about 32,768 independently
  of the 250-message cap, and the rejection message quotes an approximate count
  ("about `<n>` tokens"). Which tokenizer produces `<n>` is not public.
- **Recreation.** Uses a local approximation and emits the documented message
  and details. The message is treated as a literal to reproduce; the *estimator*
  behind `<n>` is configuration.
- **Resolved by.** Boundary probes around 32,768 tokens on inputs with known
  tokenizations.

### 6.5 Report determinism

- **Unknown.** Deterministic all-type aggregates are required, but nothing
  establishes that two analyses of the same transcript produce the same prose,
  interaction partition, or health score.
- **Recreation.** Deterministic for a given input, which is a stricter promise
  than production makes. Callers must not depend on it against production.
- **Resolved by.** Repeated production analyses of one transcript.

---

## Phase 7 — Personas

### 7.1 Failed-job error payload

- **Unknown.** No persona job and no audit reached `status:"failed"` in any
  live run, so the non-null `error` payload is **documented only**: a stable
  category such as `"provider_error"`.
- **Recreation.** `jobs.fail_job` writes exactly `"provider_error"` and sets
  `status:"failed"`, leaving `result` null. The clients type `error` as
  `null | string | object` so a future richer payload does not break them.
- **Resolved by.** A production job failure, however induced.

### 7.2 Blueprint design policy

- **Unknown.** How production designs a blueprint — which fields, which
  conditional structure, which constraints, which style axes — is model-driven
  and unspecified. Only the *schema* is tested: explicit nulls, conditional-only
  distributions, `order` covering every categorical/numeric/derived field.
- **Recreation.** A deterministic designer that satisfies the schema and the
  gate that a generated population validates with `passed:true`.
- **Resolved by.** Published blueprint design documentation, or enough
  production blueprints to characterise the policy.

### 7.3 `soft_scores` sparsity

- **Unknown.** `soft_scores` is sparse with keys ⊆ `{voice_attribution}` and
  values in [0,1]. When `voice_attribution` is present versus absent is not
  pinned.
- **Recreation.** Emits the key under a deterministic condition and always
  keeps the map within the tested key set and range.
- **Resolved by.** Production scorecards across personas with and without
  distinctive voices.

### 7.4 Enhanced `persona_id` derivation

- **Unknown.** The form `enhanced-<12 hex>` is tested; whether the hex is a
  hash of the seed, a random value, or something else is not.
- **Recreation.** Generates 12 random hex characters, so ids are unique but not
  derivable from the seed.
- **Resolved by.** Two production enhancements of the identical seed: equal ids
  imply a hash, differing ids imply randomness.

### 7.5 Job durations

- **Unknown.** Population ~52 s, enhancement ~37 s, audit ~20 s, evaluation
  ~3.5 s were observed once. They are capacity inputs, not SLOs.
- **Recreation.** Long worker leases and a 300 s default client timeout, both
  configuration. No timing promise is made to callers.
- **Resolved by.** A published SLO, or a duration distribution across many
  production runs.

---

## Phase 8 — Hardening

### 8.1 Retention and deletion

- **Unknown.** Retention windows, deletion semantics, and whether production
  exposes any delete operation are not public behavior. spec/03 explicitly
  forbids inventing public list/clear/delete operations for threads, memory
  scopes, messages, or facts.
- **Recreation.** Retains everything by default; retention is **local
  configuration** applied by operators, and no public delete route exists.
- **Resolved by.** A published retention policy or a documented deletion
  endpoint.

### 8.2 Residency and encryption at rest

- **Unknown.** Production residency guarantees and encryption details are not
  public behavioral contracts.
- **Recreation.** Storage location and encryption are deployment
  configuration. The service only guarantees what it controls: keys stored as
  HMAC lookup values, and no bearer value, WSS grant, or account identity in
  logs or tracked files.
- **Resolved by.** A published data-residency or security statement.

### 8.3 Provider/model/prompt versions

- **Unknown.** Which providers, model versions, and prompt versions production
  uses, and how it fails over between them, are not public.
- **Recreation.** Deterministic substitutes by default; provider selection,
  failover order, and retry policy are configuration. Only transient
  provider/queue failures are retried, never semantic 4xx. `router_traces`
  records the `prompt_version` behind each decision so a change is auditable.
- **Resolved by.** Published model/prompt documentation.

### 8.4 Device authorization

- **Unknown.** The Hermes plugin contains privileged device-authorization
  routes, but their gateway credential sits outside the tested customer API.
- **Recreation.** **Explicitly unsupported.** Not implemented, not typed in the
  clients, not exercised by the examples.
- **Resolved by.** Separate authorization and a tested contract; until then it
  stays out of the recreation target.

### 8.5 Hardening properties that are engineering requirements, not production behavior

- **Unknown.** Multi-tenant isolation, crash recovery, queue duplication,
  prompt-injection resistance, and provider failover cannot be established
  against production with one key — spec/07 lists them as required engineering
  properties precisely because they are not observed production behavior.
- **Recreation.** Enforced and proven locally:
  `service/tests/test_billing_isolation.py` covers cross-tenant reads and the
  billing paths, `service/tests/test_concurrency.py` covers same-key ingest
  replay and stale-epoch atomicity, `scheduler.recover()` covers schedule
  recovery after restart, and `billing.reconcile_abandoned` covers reservations
  left by a crashed worker. These are local guarantees stated as such.
- **Resolved by.** Nothing production can show; they remain internal gates.
