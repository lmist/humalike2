"""Credit reservation/capture ledger and usage projection (spec/02 §Billing).

A billable command reserves before model work and captures after success.
Superseded, short-circuited, and terminal polling paths never capture.
Component prices are configuration, not stable public pricing.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from .config import settings
from .db import session
from .ids import new_uuid
from .storage import CreditReservation, Owner, RequestCounter, UsageEvent
from .timefmt import utcnow

COMPONENTS = (
    "personas", "social-learning", "social-memory",
    "social-observability", "theoryofmind", "turn-taking",
)

_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class InsufficientCredits(Exception):
    pass


def reserve(owner_id: str, component: str) -> str:
    """Reserve credits before billable work. Raises InsufficientCredits."""
    price = settings.prices[component]
    now = utcnow()
    with session() as s:
        owner = s.get(Owner, owner_id, with_for_update=False)
        reserved = s.execute(
            select(func.coalesce(func.sum(CreditReservation.credits), 0))
            .where(CreditReservation.owner_id == owner_id,
                   CreditReservation.state == "reserved")
        ).scalar_one()
        if owner is None or owner.credits_balance - reserved < price:
            raise InsufficientCredits()
        rid = new_uuid()
        s.add(CreditReservation(id=rid, owner_id=owner_id, component=component,
                                credits=price, state="reserved",
                                created_at=now, updated_at=now))
    return rid


def capture(reservation_id: str) -> None:
    now = utcnow()
    with session() as s:
        r = s.get(CreditReservation, reservation_id)
        if r is None or r.state != "reserved":
            return
        r.state = "captured"
        r.updated_at = now
        owner = s.get(Owner, r.owner_id)
        owner.credits_balance -= r.credits
        s.add(UsageEvent(owner_id=r.owner_id, component=r.component,
                         credits=r.credits, at=now))


def release(reservation_id: str) -> None:
    with session() as s:
        r = s.get(CreditReservation, reservation_id)
        if r is None or r.state != "reserved":
            return
        r.state = "released"
        r.updated_at = utcnow()


def reconcile_abandoned(older_than_seconds: float = 600.0) -> int:
    """Release reservations abandoned by crashed workers (spec/06)."""
    cutoff = utcnow() - timedelta(seconds=older_than_seconds)
    released = 0
    with session() as s:
        rows = s.execute(
            select(CreditReservation).where(
                CreditReservation.state == "reserved",
                CreditReservation.created_at < cutoff)
        ).scalars().all()
        for r in rows:
            r.state = "released"
            r.updated_at = utcnow()
            released += 1
    return released


def bill(owner_id: str, component: str) -> None:
    """Reserve+capture in one step for synchronous billable commands."""
    capture(reserve(owner_id, component))


def count_request(owner_id: str) -> None:
    """Increment the per-UTC-day request counter for the daily series."""
    day = utcnow().strftime("%Y-%m-%d")
    with session() as s:
        row = s.get(RequestCounter, (owner_id, day))
        if row is None:
            s.add(RequestCounter(owner_id=owner_id, day=day, requests=1))
        else:
            row.requests += 1


def usage_summary(owner_id: str) -> dict:
    """Exact UsageSummary shape (spec/03 §Identity and usage)."""
    with session() as s:
        rows = s.execute(
            select(UsageEvent.component,
                   func.count(UsageEvent.id),
                   func.coalesce(func.sum(UsageEvent.credits), 0))
            .where(UsageEvent.owner_id == owner_id)
            .group_by(UsageEvent.component)
        ).all()
        per_component = [
            {"component": component, "calls": int(calls), "credits": int(credits)}
            for component, calls, credits in sorted(rows)
        ]
        total_calls = sum(r["calls"] for r in per_component)
        total_credits = sum(r["credits"] for r in per_component)

        today = utcnow().date()
        days = [(today - timedelta(days=offset)) for offset in range(6, -1, -1)]
        counters = {
            row.day: row.requests
            for row in s.execute(
                select(RequestCounter).where(RequestCounter.owner_id == owner_id)
            ).scalars().all()
        }
        daily_series = [
            {"date": _DAY_NAMES[d.weekday()], "requests": int(counters.get(d.strftime("%Y-%m-%d"), 0))}
            for d in days
        ]
    return {
        "total_calls": total_calls,
        "total_credits": total_credits,
        "per_component": per_component,
        "daily_series": daily_series,
    }
