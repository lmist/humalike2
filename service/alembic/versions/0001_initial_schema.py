"""Initial schema: the complete phase 0-8 table set.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-20

Written by hand (no database or autogenerate round-trip required) so the
mapping from tables to the spec/07 phases stays explicit and reviewable. Each
`_phase_*` helper below owns exactly the tables that phase introduces, and
`downgrade()` drops them in reverse phase order so a partial rollback of a
later phase never strands an earlier phase's data (docs/runbooks/rollback.md).

Phase map (spec/07 §Phase 0 … §Phase 8):

    phase 0-1  identity, tenancy, credits   api_keys, owners, usage_events,
                                            credit_reservations, request_counters
    phase 2-3  threads and realtime         threads, thread_messages, schedules,
                                            router_traces
    phase 4    Social Memory                memory_messages, memory_facts,
                                            idempotency_records
    phase 5    Social Learning / foresee    learned_profiles
    phase 6    observability and audit      audit_runs, reports
    phase 7    personas                     jobs
    phase 8    hardening                    outbox

This revision creates the whole set in one step because phases 0-8 of the
recreation ship from a single schema baseline; later per-phase migrations
stack on top of it and are the ones a per-phase rollback reverts.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


# --------------------------------------------------------------------------
# Phase 0-1 — Live contract harness, identity, tenancy, and credits
# spec/07 §Phase 0, §Phase 1; spec/02 §Authentication, §Billing
# --------------------------------------------------------------------------
def _phase_0_1_upgrade() -> None:
    # Bearer keys are stored as HMAC lookup values only; no plaintext column
    # exists so a key can never enter the database or a log (spec/02).
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key_hmac", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_keys_key_hmac", "api_keys", ["key_hmac"], unique=True)
    op.create_index("ix_api_keys_owner_id", "api_keys", ["owner_id"], unique=False)

    # The owner principal every repository query and command is scoped by.
    op.create_table(
        "owners",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("credits_balance", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # One row per captured charge. Free paths (events, terminal polling,
    # superseded respond, short-circuited submit) never write here.
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("component", sa.String(length=64), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_events_at", "usage_events", ["at"], unique=False)
    op.create_index("ix_usage_events_owner_id", "usage_events", ["owner_id"], unique=False)

    # Reserve before model work, capture after success, release on failure
    # (spec/06 §Command transaction).
    op.create_table(
        "credit_reservations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("component", sa.String(length=64), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credit_reservations_owner_id", "credit_reservations",
                    ["owner_id"], unique=False)

    # Backs usage-summary's seven-entry zero-filled UTC daily series (spec/03).
    op.create_table(
        "request_counters",
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("owner_id", "day"),
    )


def _phase_0_1_downgrade() -> None:
    op.drop_table("request_counters")
    op.drop_index("ix_credit_reservations_owner_id", table_name="credit_reservations")
    op.drop_table("credit_reservations")
    op.drop_index("ix_usage_events_owner_id", table_name="usage_events")
    op.drop_index("ix_usage_events_at", table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_table("owners")
    op.drop_index("ix_api_keys_owner_id", table_name="api_keys")
    op.drop_index("ix_api_keys_key_hmac", table_name="api_keys")
    op.drop_table("api_keys")


# --------------------------------------------------------------------------
# Phase 2-3 — Thread state, realtime delivery, model-backed turn-taking
# spec/07 §Phase 2, §Phase 3; spec/03 §Thread creation, §Reply refinement
# --------------------------------------------------------------------------
def _phase_2_3_upgrade() -> None:
    # turn_epoch is the atomicity anchor for respond supersession; the
    # integration columns hold the selected memory bank (preserved when a
    # later reopen omits integrations) and the Social Signals scope/channel.
    op.create_table(
        "threads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("turn_epoch", sa.Integer(), nullable=False),
        sa.Column("memory_bank_id", sa.String(length=255), nullable=True),
        sa.Column("signals_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_threads_owner_id", "threads", ["owner_id"], unique=False)

    op.create_table(
        "thread_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("thread_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("sender", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("has_media", sa.Boolean(), nullable=False),
        sa.Column("client_ts", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_thread_messages_owner_id", "thread_messages",
                    ["owner_id"], unique=False)
    op.create_index("ix_thread_messages_thread_id", "thread_messages",
                    ["thread_id"], unique=False)

    # One row per scheduled bubble. reply_group ties the N+3 delivery
    # sequence together; deliver_at is indexed for scheduler recovery after a
    # restart (spec/06 §Reliability and scaling).
    op.create_table(
        "schedules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("thread_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("reply_group", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("deliver_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedules_deliver_at", "schedules", ["deliver_at"], unique=False)
    op.create_index("ix_schedules_owner_id", "schedules", ["owner_id"], unique=False)
    op.create_index("ix_schedules_reply_group", "schedules", ["reply_group"], unique=False)
    op.create_index("ix_schedules_thread_id", "schedules", ["thread_id"], unique=False)

    # Phase 3 decision traces. Internal only: they never alter public fields,
    # and prompt_version records which deterministic substitute produced a
    # decision (spec/08 open question 8).
    op.create_table(
        "router_traces",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("thread_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("scores_json", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_router_traces_thread_id", "router_traces",
                    ["thread_id"], unique=False)


def _phase_2_3_downgrade() -> None:
    op.drop_index("ix_router_traces_thread_id", table_name="router_traces")
    op.drop_table("router_traces")
    op.drop_index("ix_schedules_thread_id", table_name="schedules")
    op.drop_index("ix_schedules_reply_group", table_name="schedules")
    op.drop_index("ix_schedules_owner_id", table_name="schedules")
    op.drop_index("ix_schedules_deliver_at", table_name="schedules")
    op.drop_table("schedules")
    op.drop_index("ix_thread_messages_thread_id", table_name="thread_messages")
    op.drop_index("ix_thread_messages_owner_id", table_name="thread_messages")
    op.drop_table("thread_messages")
    op.drop_index("ix_threads_owner_id", table_name="threads")
    op.drop_table("threads")


# --------------------------------------------------------------------------
# Phase 4 — Social Memory
# spec/07 §Phase 4; spec/03 §Social Memory; spec/02 §Idempotency
# --------------------------------------------------------------------------
def _phase_4_upgrade() -> None:
    # Append-only raw transcript. The (owner, scope, seq) unique constraint is
    # what makes ordering and "no duplicate replay" checkable in storage
    # rather than only in the engine.
    op.create_table(
        "memory_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "scope_id", "seq"),
    )
    op.create_index("ix_memory_messages_owner_id", "memory_messages",
                    ["owner_id"], unique=False)
    op.create_index("ix_memory_messages_scope_id", "memory_messages",
                    ["scope_id"], unique=False)

    # Subject-centric facts: `subject` is the attributed subject even when
    # another speaker stated the fact, `evidence_seq` links back to the raw
    # message, `contradicts_id` records supersession instead of deleting.
    op.create_table(
        "memory_facts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("speaker", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("evidence_seq", sa.Integer(), nullable=False),
        sa.Column("contradicts_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_facts_owner_id", "memory_facts", ["owner_id"], unique=False)
    op.create_index("ix_memory_facts_scope_id", "memory_facts", ["scope_id"], unique=False)

    # First-write-wins keyed by (owner, key) across scopes — the composite
    # primary key is the contract, not a per-scope index (spec/02).
    op.create_table(
        "idempotency_records",
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("owner_id", "key"),
    )


def _phase_4_downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_index("ix_memory_facts_scope_id", table_name="memory_facts")
    op.drop_index("ix_memory_facts_owner_id", table_name="memory_facts")
    op.drop_table("memory_facts")
    op.drop_index("ix_memory_messages_scope_id", table_name="memory_messages")
    op.drop_index("ix_memory_messages_owner_id", table_name="memory_messages")
    op.drop_table("memory_messages")


# --------------------------------------------------------------------------
# Phase 5 — Social Learning and foresee
# spec/07 §Phase 5; spec/04 §Social Learning
# --------------------------------------------------------------------------
def _phase_5_upgrade() -> None:
    # Learned style is refreshed independently from durable factual memory, so
    # it lives in its own table and never in memory_facts (spec/04).
    # foresee itself is stateless and adds no table.
    op.create_table(
        "learned_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("profile_json", sa.Text(), nullable=False),
        sa.Column("prompt_block", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_learned_profiles_owner_id", "learned_profiles",
                    ["owner_id"], unique=False)


def _phase_5_downgrade() -> None:
    op.drop_index("ix_learned_profiles_owner_id", table_name="learned_profiles")
    op.drop_table("learned_profiles")


# --------------------------------------------------------------------------
# Phase 6 — Social Observability and audit
# spec/07 §Phase 6; spec/04 §Social Observability, §Full audit
# --------------------------------------------------------------------------
def _phase_6_upgrade() -> None:
    # Each projection section is independently nullable so the audit can
    # become non-null monotonically in report <= read <= verdicts <= replies
    # order without exposing status or stage (spec/04).
    op.create_table(
        "audit_runs",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("agent_guess", sa.Text(), nullable=True),
        sa.Column("launched", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("transcript_json", sa.Text(), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=True),
        sa.Column("read_json", sa.Text(), nullable=True),
        sa.Column("verdicts_json", sa.Text(), nullable=True),
        sa.Column("replies_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_audit_runs_owner_id", "audit_runs", ["owner_id"], unique=False)

    # Owner-scoped report storage. analyze deliberately exposes no id, so this
    # table is reachable only from audit-side flows (spec/08 open question 1).
    op.create_table(
        "reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_owner_id", "reports", ["owner_id"], unique=False)


def _phase_6_downgrade() -> None:
    op.drop_index("ix_reports_owner_id", table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_audit_runs_owner_id", table_name="audit_runs")
    op.drop_table("audit_runs")


# --------------------------------------------------------------------------
# Phase 7 — Personas
# spec/07 §Phase 7; spec/04 §Persona generation; spec/06 §Asynchronous resources
# --------------------------------------------------------------------------
def _phase_7_upgrade() -> None:
    # One table for every async persona kind (population | enhancement |
    # evaluation). request_json is the durable echo the repository projections
    # replay; lease_until is the worker lease; error_json holds the documented
    # "provider_error" category only (spec/08 open question 9).
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("progress_json", sa.Text(), nullable=True),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_json", sa.Text(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_owner_id", "jobs", ["owner_id"], unique=False)


def _phase_7_downgrade() -> None:
    op.drop_index("ix_jobs_owner_id", table_name="jobs")
    op.drop_table("jobs")


# --------------------------------------------------------------------------
# Phase 8 — Hardening
# spec/07 §Phase 8; spec/06 §Command transaction
# --------------------------------------------------------------------------
def _phase_8_upgrade() -> None:
    # Written in the same transaction as schedules and job state so delivery
    # or work publication cannot be lost between commit and queue publish.
    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def _phase_8_downgrade() -> None:
    op.drop_table("outbox")


def upgrade() -> None:
    _phase_0_1_upgrade()
    _phase_2_3_upgrade()
    _phase_4_upgrade()
    _phase_5_upgrade()
    _phase_6_upgrade()
    _phase_7_upgrade()
    _phase_8_upgrade()


def downgrade() -> None:
    _phase_8_downgrade()
    _phase_7_downgrade()
    _phase_6_downgrade()
    _phase_5_downgrade()
    _phase_4_downgrade()
    _phase_2_3_downgrade()
    _phase_0_1_downgrade()
