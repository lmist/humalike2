"""Durable state (spec/06 §Durable state).

All resources are keyed by an immutable owner derived from the verified
bearer; clients never submit an owner id (spec/01 §Ownership and isolation).
JSON columns are serialized text for SQLite/PostgreSQL portability.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def loads(raw: str | None):
    return None if raw is None else json.loads(raw)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_hmac: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Owner(Base):
    __tablename__ = "owners"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    credits_balance: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UsageEvent(Base):
    """One billable capture (spec/02 §Billing). Free paths never write here."""
    __tablename__ = "usage_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    component: Mapped[str] = mapped_column(String(64))
    credits: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class CreditReservation(Base):
    """Reserve before model work, capture after (spec/06 §Command transaction)."""
    __tablename__ = "credit_reservations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    component: Mapped[str] = mapped_column(String(64))
    credits: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default="reserved")  # reserved|captured|released
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RequestCounter(Base):
    """Per-owner per-UTC-day request counter for the usage daily series."""
    __tablename__ = "request_counters"
    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD (UTC)
    requests: Mapped[int] = mapped_column(Integer, default=0)


class Thread(Base):
    __tablename__ = "threads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    turn_epoch: Mapped[int] = mapped_column(Integer, default=0)
    memory_bank_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signals_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class ThreadMessage(Base):
    """Inbound batch messages, appended in accepted order."""
    __tablename__ = "thread_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    epoch: Mapped[int] = mapped_column(Integer)
    sender: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    has_media: Mapped[bool] = mapped_column(Boolean, default=False)
    client_ts: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Schedule(Base):
    """Scheduled reply bubbles (spec/03 §Reply refinement and scheduling)."""
    __tablename__ = "schedules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    reply_group: Mapped[str] = mapped_column(String(36), index=True)
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    deliver_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(16), default="scheduled")  # scheduled|delivered
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RouterTrace(Base):
    """Internal decision trace (spec/05); never alters public fields."""
    __tablename__ = "router_traces"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(64))
    epoch: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(16))
    scores_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default="det-1")
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MemoryMessage(Base):
    """Append-only owner/scope ordered raw messages (spec/05 §Social Memory)."""
    __tablename__ = "memory_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    scope_id: Mapped[str] = mapped_column(String(255), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("owner_id", "scope_id", "seq"),)


class MemoryFact(Base):
    """Subject-centric facts with evidence links and contradiction metadata."""
    __tablename__ = "memory_facts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    scope_id: Mapped[str] = mapped_column(String(255), index=True)
    subject: Mapped[str] = mapped_column(Text)
    speaker: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    evidence_seq: Mapped[int] = mapped_column(Integer)
    contradicts_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(Base):
    """First-write-wins keyed by (owner, key) across scopes (spec/02)."""
    __tablename__ = "idempotency_records"
    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Job(Base):
    """Async resources: persona population/enhancement/evaluation (spec/04)."""
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # population|enhancement|evaluation
    status: Mapped[str] = mapped_column(String(16), default="pending")
    progress_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditRun(Base):
    """Prepared/launched audits with independently nullable sections (spec/04)."""
    __tablename__ = "audit_runs"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_name: Mapped[str] = mapped_column(Text)
    agent_guess: Mapped[str | None] = mapped_column(Text, nullable=True)
    launched: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="prepared")  # prepared|queued|completed
    transcript_json: Mapped[str] = mapped_column(Text)
    report_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdicts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    replies_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StoredReport(Base):
    """Owner-scoped report storage; analyze exposes no public linkage."""
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    report_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LearnedProfile(Base):
    """Learned style kept separate from durable factual memory (spec/05)."""
    __tablename__ = "learned_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(Text, default="")
    profile_json: Mapped[str] = mapped_column(Text)
    prompt_block: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Outbox(Base):
    """Transactional outbox (spec/06 §Command transaction)."""
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
