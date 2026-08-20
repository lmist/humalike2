"""Lease-based asynchronous job runner (spec/06 §Asynchronous resources).

Population, enhancement, evaluation, and audit work runs off the request
path. Workers claim jobs with leases and idempotent stages; polling is a
read-only projection and never bills. Handlers are registered per kind by
the owning module.
"""

from __future__ import annotations

import asyncio
import traceback
from datetime import timedelta
from typing import Awaitable, Callable

from sqlalchemy import select

from . import metrics
from .db import session
from .storage import Job, dumps
from .timefmt import utcnow

Handler = Callable[[str], Awaitable[None]]

_handlers: dict[str, Handler] = {}
_LEASE = timedelta(seconds=120)


def register_handler(kind: str, handler: Handler) -> None:
    _handlers[kind] = handler


def claim_next() -> Job | None:
    now = utcnow()
    with session() as s:
        job = s.execute(
            select(Job).where(
                Job.status.in_(("pending", "running")),
                (Job.lease_until.is_(None)) | (Job.lease_until < now),
                Job.kind.in_(tuple(_handlers.keys()) or ("",)),
            ).order_by(Job.created_at).limit(1)
        ).scalar_one_or_none()
        if job is None:
            return None
        job.lease_until = now + _LEASE
        if job.status == "pending":
            job.status = "running"
        job.updated_at = now
        return job


def fail_job(job_id: str, category: str = "provider_error") -> None:
    """Documented default failure category (spec/04), not live-proven."""
    with session() as s:
        job = s.get(Job, job_id)
        if job is not None and job.status not in ("succeeded", "failed"):
            job.status = "failed"
            job.error_json = dumps(category)
            job.updated_at = utcnow()


async def worker_loop(poll_seconds: float = 0.2) -> None:
    while True:
        job = None
        try:
            job = claim_next()
        except Exception:
            traceback.print_exc()
        if job is None:
            await asyncio.sleep(poll_seconds)
            continue
        handler = _handlers.get(job.kind)
        if handler is None:
            await asyncio.sleep(poll_seconds)
            continue
        started = utcnow()
        try:
            await handler(job.id)
            metrics.record_job(job.kind, "succeeded",
                               (utcnow() - started).total_seconds() * 1000.0)
        except Exception:
            traceback.print_exc()
            fail_job(job.id)
            metrics.record_job(job.kind, "failed",
                               (utcnow() - started).total_seconds() * 1000.0)


def start_workers(count: int = 2) -> list[asyncio.Task]:
    return [asyncio.create_task(worker_loop()) for _ in range(count)]
