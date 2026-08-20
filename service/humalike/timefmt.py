"""Timestamp serialization (spec/02 §HTTP and serialization).

Every HTTP and WSS event timestamp is YYYY-MM-DDTHH:MM:SS.ffffffZ
(microsecond precision, literal Z). The sole exception is the WSS
attached.server_time which uses the .ffffff+00:00 offset form.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ts(dt: datetime) -> str:
    """Microsecond UTC with a literal Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def ts_offset(dt: datetime) -> str:
    """Microsecond UTC with a +00:00 offset (attached.server_time only)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "+00:00"


def now_ts() -> str:
    return ts(utcnow())
