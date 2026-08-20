"""Timestamp serialization (spec/02 §HTTP and serialization).

Every HTTP and WSS event timestamp is YYYY-MM-DDTHH:MM:SS.ffffffZ
(microsecond precision, literal Z). The sole exception is the WSS
attached.server_time which uses the .ffffff+00:00 offset form.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime) -> datetime:
    """Normalize to UTC-aware.

    SQLite round-trips ``DateTime(timezone=True)`` columns as naive
    datetimes. Every stored instant is UTC, so a naive value is re-tagged as
    UTC rather than passed to ``astimezone`` (which would interpret it as
    host-local time and shift it by the host's UTC offset).
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ts(dt: datetime) -> str:
    """Microsecond UTC with a literal Z."""
    return aware(dt).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def ts_offset(dt: datetime) -> str:
    """Microsecond UTC with a +00:00 offset (attached.server_time only)."""
    return aware(dt).strftime("%Y-%m-%dT%H:%M:%S.%f") + "+00:00"


def now_ts() -> str:
    return ts(utcnow())
