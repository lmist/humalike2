# Rollback runbook

Per-phase rollback for the Humalike API recreation (spec/07 §Delivery
discipline: each phase ships rollback steps). Each section says what to switch
off, what to revert, which Alembic revision the phase's schema belongs to, and
what happens to data in flight.

Two rules apply to every phase:

- **Disable before you downgrade.** Stop the writers first, let in-flight work
  drain or expire, then touch the schema. A downgrade under live writers loses
  the rows that arrive between the two steps.
- **A schema downgrade is destructive.** `alembic downgrade` drops the tables
  the target revision created. Take a backup first; there is no compensating
  "undo" for a dropped table.

## Revision map

The baseline revision `0001_initial_schema` creates the whole phase 0-8 table
set in per-phase sections (`service/alembic/versions/0001_initial_schema.py`).
Later per-phase migrations stack on top of it, and those are what a per-phase
rollback normally reverts. Downgrading past the baseline empties the database.

| Phase | Tables introduced | Revision that owns them |
| --- | --- | --- |
| 0-1 | `api_keys`, `owners`, `usage_events`, `credit_reservations`, `request_counters` | `0001_initial_schema` (`_phase_0_1_upgrade`) |
| 2-3 | `threads`, `thread_messages`, `schedules`, `router_traces` | `0001_initial_schema` (`_phase_2_3_upgrade`) |
| 4 | `memory_messages`, `memory_facts`, `idempotency_records` | `0001_initial_schema` (`_phase_4_upgrade`) |
| 5 | `learned_profiles` | `0001_initial_schema` (`_phase_5_upgrade`) |
| 6 | `audit_runs`, `reports` | `0001_initial_schema` (`_phase_6_upgrade`) |
| 7 | `jobs` | `0001_initial_schema` (`_phase_7_upgrade`) |
| 8 | `outbox` | `0001_initial_schema` (`_phase_8_upgrade`) |

Commands run from `service/`. `HUMALIKE_DATABASE_URL` selects the target, or
pass `-x url=...` for a one-off:

```sh
cd service
alembic current                 # what is deployed now
alembic history --verbose       # the chain
alembic downgrade <revision>    # revert to that revision
alembic downgrade -1            # revert exactly one migration
alembic upgrade head            # roll forward again
```

Always capture `alembic current` **before** rolling back; it is the only record
of where to roll forward to.

## Phase 0 — Live contract harness

**Disable.** Nothing serves traffic in this phase. Point
`HUMALIKE_API_URL` back at production (or at the previous candidate) so the
suites stop targeting the rolled-back build.

**Revert.** Redeploy the previous image. The request-id middleware and error
serializers are the only application code; both are stateless.

**Schema.** None.

**Data safety.** None at risk. Do not "fix" a failing suite by editing test
expectations: the suites are the parity oracle, and a change there is a change
to the contract (spec/08).

## Phase 1 — Identity, tenancy, and credits

**Disable.** Stop issuing new API keys. If the rollback is due to a billing
defect, set every component price to `0` via `HUMALIKE_PRICE_*` so requests
keep working while nothing is charged — much safer than disabling
authentication.

**Revert.** Redeploy the previous image. Reconcile before and after:

```sh
python -c "from humalike.billing import reconcile_abandoned; print(reconcile_abandoned(0.0))"
```

That releases reservations that will otherwise sit `reserved` forever and
suppress a tenant's available balance.

**Schema.**

```sh
alembic downgrade <revision-before-the-phase-1-migration>
```

**Data safety.** `owners.credits_balance` is the account of record and
`usage_events` is the audit trail; a downgrade that drops either destroys
billing history. Dump both tables first. A reservation left in `reserved`
state charges nobody but does hold balance, so prefer releasing over deleting.
Never restore `api_keys` from a foreign backup: rows are HMAC lookup values
under `HUMALIKE_SECRET`, and a backup taken under a different secret silently
authenticates nobody.

## Phase 2 — Thread state and realtime delivery

**Disable.** In order:

1. Stop accepting new replies — take `respond` out of the load balancer, or
   deploy with the turn-taking router unmounted, so no new rows enter
   `schedules`.
2. Let the delivery scheduler drain. Every pending bubble is at most a few
   seconds of pacing plus its `deliver_at`; wait until
   `select count(*) from schedules where status = 'scheduled'` reaches zero,
   or until the oldest `deliver_at` is comfortably in the past.
3. Then stop the process. Attached sockets close on shutdown; clients recover
   by reopening the thread for a fresh grant, which is the documented recovery
   path for an expired grant already.

**Revert.** Redeploy the previous image. On boot, `scheduler.recover()` re-arms
every row still marked `scheduled` from durable state, so a rollback that
skipped step 2 replays the undelivered tail rather than losing it — bubbles
whose `deliver_at` has passed are delivered immediately, late but complete.

```sql
-- Optional: drop the undeliverable tail instead of replaying it late.
update schedules set status = 'delivered' where status = 'scheduled' and deliver_at < now();
```

**Schema.** `alembic downgrade <revision-before-the-phase-2-migration>`.

**Data safety.** Dropping `threads` invalidates every outstanding WSS grant and
every client-held `thread_id`; callers see their next `open_thread` create a
*new* thread with the same supplied UUID rather than reopen. Dropping
`schedules` with rows still `scheduled` silently cancels those deliveries — the
client already received a 200 listing them. Rotating `HUMALIKE_SECRET` as part
of a rollback invalidates all in-flight grants immediately; sockets already
attached survive, later connections close with code 4000.

## Phase 3 — Model-backed turn-taking

**Disable.** This phase replaces deterministic substitutes with model-backed
decisions, so the rollback is usually to the substitutes rather than to no
service: unset the model provider configuration and let `humalike.engine.router`
and the naturalizer run their deterministic paths. Pacing, epochs, and delivery
are untouched — they belong to phase 2.

**Revert.** Redeploy the previous image. Nothing needs draining beyond the
phase 2 schedule drain, because decisions are synchronous.

**Schema.** `router_traces` is internal telemetry with no public field
depending on it; it can be dropped independently:

```sh
alembic downgrade <revision-before-the-phase-3-migration>
```

**Data safety.** Keep `router_traces` if you are rolling back *because* of a
decision defect — it holds the scores and prompt version behind each decision
and is the only evidence of what the router did. Rolling back model policy
changes what `submit_messages` decides and how `respond` splits bubbles; both
are within contract (1-5 bubbles, merge-not-truncate), so no client change is
required.

## Phase 4 — Social Memory

**Disable.** Stop `ingest` first, then `recall`/`ask`. Threads with a
`social_memory` integration keep working: `recalled_context` degrades to `""`,
which is a valid response for a scope with nothing to recall.

**Revert.** Redeploy the previous image.

**Schema.** `alembic downgrade <revision-before-the-phase-4-migration>`.

**Data safety.** This is the most destructive downgrade in the set.
`memory_messages` holds original bodies that no other table reproduces, and
`memory_facts` holds the attribution and contradiction links derived from
them; both must be dumped before a downgrade. Dropping `idempotency_records`
breaks first-write-wins: a client that retries an `Idempotency-Key` after the
rollback ingests the body a second time, duplicating facts. If the rollback is
schema-only, keep `idempotency_records` even when you drop everything else, or
tell callers to rotate their keys.

## Phase 5 — Social Learning and foresee

**Disable.** Unmount the `social-learning` and `foresee` routers. Callers get
404/405 rather than a wrong profile, which is the safer failure for a route
whose output feeds a system prompt.

**Revert.** Redeploy the previous image. foresee is stateless, so it needs no
drain.

**Schema.** `alembic downgrade <revision-before-the-phase-5-migration>` drops
`learned_profiles`.

**Data safety.** Learned style is deliberately separate from durable factual
memory, so dropping `learned_profiles` loses only style that a re-extract can
rebuild from the same transcript — no fact is lost. That separation is what
makes this the cheapest rollback in the set; do not "simplify" it by folding
profiles into `memory_facts`.

## Phase 6 — Observability and audit

**Disable.** Stop `audit_launch` first so no new runs enter the queue, and
leave `audit-run` polling up: the projection is a read-only view, polling is
free, and in-flight clients need it to observe whatever sections completed.
`analyze` is synchronous and can be stopped independently.

**Revert.** Let claimed audits finish (about 20 s live) or let their worker
leases expire. A partially completed run stays readable — sections are
independently nullable, so a client sees `report` set with `verdicts` still
`null` rather than a broken document.

**Schema.** `alembic downgrade <revision-before-the-phase-6-migration>` drops
`audit_runs` and `reports`.

**Data safety.** Dropping `audit_runs` invalidates every `run_id` a client
holds; their next `audit-run` poll returns 400 `unknown run`, which is the
documented shape for an unknown run and needs no client change. `reports` is
owner-scoped storage that the tested `analyze` flow exposes no identifier for
(spec/08 open question 1), so dropping it removes no reachable public state —
but it is also the only copy of audit-side reports, so dump it if reports are
retained for anything.

## Phase 7 — Personas

**Disable.** Pause the persona job kinds rather than stopping the workers:
deregister the handlers for `population`, `enhancement`, and `evaluation` so
`humalike.jobs.claim_next` no longer selects them. Queued rows stay `pending`
and are picked up when the handlers are registered again — this is the
reversible step, and it leaves audit work (phase 6) running.

Then stop accepting new work by unmounting the persona action routes while
leaving the repository `by-id` routes up, so clients holding an id can keep
polling. Repository polling is free.

**Revert.** Redeploy the previous image and re-register the handlers. Workers
claim with leases and idempotent stages, so a job interrupted mid-flight is
re-claimed after its lease expires rather than lost or duplicated. Jobs that
cannot be resumed should be failed explicitly:

```sh
python -c "from humalike.jobs import fail_job; fail_job('<job-id>')"
```

which sets `status:"failed"` with the documented `"provider_error"` category —
the only failure payload the spec carries, and one no live run has produced.

**Schema.** `alembic downgrade <revision-before-the-phase-7-migration>` drops
`jobs`.

**Data safety.** Dropping `jobs` destroys population, enhancement, *and*
evaluation resources at once, since all three share the table; every
outstanding `id` a client holds starts returning `null` (the documented shape
for a missing valid UUID), so clients degrade to "not found" rather than to an
error. Generated populations are expensive — roughly 580-640 credits for a
full-size run — so dump `jobs` before dropping it even if the rollback is
otherwise routine.

## Phase 8 — Hardening

**Disable.** Phase 8 adds no public surface. Roll back the specific hardening
change: restore the previous retention window, residency setting, provider
failover order, or rate-limit configuration. Every one of these is local
configuration, not established production behavior
(`docs/unresolved-behavior.md`, phase 8), so reverting one changes no tested
response.

**Revert.** Redeploy the previous image and re-run both suites against the
candidate before declaring the rollback complete:

```sh
HUMALIKE_API_URL=http://<candidate> ./tests/realtime/run.sh
HUMALIKE_API_URL=http://<candidate> ./tests/intelligence/run.sh
```

Zero failures and zero skips. Exit code 3 is credit depletion — a budget
blocker to be reported as such, never reinterpreted as a regression.

**Schema.** `alembic downgrade <revision-before-the-phase-8-migration>` drops
`outbox`.

**Data safety.** Drain the outbox before dropping it: rows with
`processed_at is null` are committed side effects whose publication has not
happened yet, so dropping the table loses exactly the deliveries the outbox
exists to protect.

```sql
select count(*) from outbox where processed_at is null;   -- must be 0 first
```

## After any rollback

1. `alembic current` matches the revision the running image expects.
2. `select count(*) from credit_reservations where state = 'reserved'` is not
   growing, and the leak-detector panel on `docs/dashboards/billing.json` sits
   at zero.
3. `select count(*) from schedules where status = 'scheduled'` is either zero
   or draining.
4. The realtime suite passes end to end: 83 passed, 0 failed, 0 skipped.
5. `docs/unresolved-behavior.md` still describes the behavior actually
   deployed — a rollback that reverts an implementation choice usually reverts
   an entry there too.
