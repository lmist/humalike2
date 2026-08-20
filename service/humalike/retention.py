"""Retention and deletion controls (spec/05 §Model operations and safety).

No public delete route exists (spec/01: callers reset by choosing a new
scope), but the recreation MUST support internal deletion/retention even so.
Windows are configurable documented defaults (ADR hum-ygkw), never claimed
as production policy.
"""

from __future__ import annotations

import os
from datetime import timedelta

from sqlalchemy import delete, select

from .db import session
from .storage import (
    AuditRun,
    IdempotencyRecord,
    Job,
    LearnedProfile,
    MemoryFact,
    MemoryMessage,
    Outbox,
    RouterTrace,
    Schedule,
    StoredReport,
    Thread,
    ThreadMessage,
)
from .timefmt import utcnow

# Documented-default windows (days); operator configuration.
TRACE_RETENTION_DAYS = int(os.environ.get("HUMALIKE_TRACE_RETENTION_DAYS", "30"))
OUTBOX_RETENTION_DAYS = int(os.environ.get("HUMALIKE_OUTBOX_RETENTION_DAYS", "7"))

_OWNER_TABLES = (
    Thread, ThreadMessage, Schedule, RouterTrace, MemoryMessage, MemoryFact,
    IdempotencyRecord, Job, AuditRun, StoredReport, LearnedProfile,
)


def purge_owner(owner_id: str) -> dict[str, int]:
    """Internal per-owner deletion control. Returns rows removed per table."""
    removed: dict[str, int] = {}
    with session() as s:
        for table in _OWNER_TABLES:
            result = s.execute(delete(table).where(table.owner_id == owner_id))
            removed[table.__tablename__] = result.rowcount or 0
    return removed


def sweep() -> dict[str, int]:
    """Apply retention windows to internal byproducts (traces, outbox)."""
    now = utcnow()
    removed: dict[str, int] = {}
    with session() as s:
        cutoff = now - timedelta(days=TRACE_RETENTION_DAYS)
        result = s.execute(delete(RouterTrace).where(RouterTrace.created_at < cutoff))
        removed["router_traces"] = result.rowcount or 0
        cutoff = now - timedelta(days=OUTBOX_RETENTION_DAYS)
        result = s.execute(
            delete(Outbox).where(Outbox.processed_at.is_not(None),
                                 Outbox.created_at < cutoff))
        removed["outbox"] = result.rowcount or 0
    return removed


def owner_data_inventory(owner_id: str) -> dict[str, int]:
    """Row counts per table for an owner (supports deletion verification)."""
    counts: dict[str, int] = {}
    with session() as s:
        for table in _OWNER_TABLES:
            rows = s.execute(select(table).where(table.owner_id == owner_id)).scalars().all()
            counts[table.__tablename__] = len(rows)
    return counts
