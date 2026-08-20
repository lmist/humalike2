"""Timestamp serialization must not depend on the host's local timezone.

SQLite returns ``DateTime(timezone=True)`` columns as naive datetimes. Before
``timefmt.aware`` existed, ``ts()`` passed those through ``astimezone``, which
treats a naive value as host-local time and shifted every stored timestamp by
the host's UTC offset (invisible on UTC hosts; a 3h skew on UTC+3).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from humalike.timefmt import aware, ts, ts_offset


@pytest.fixture
def non_utc_host(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Beirut")  # UTC+3 in August
    time.tzset()
    yield
    monkeypatch.delenv("TZ", raising=False)
    time.tzset()


def test_naive_is_treated_as_utc(non_utc_host):
    instant = datetime(2026, 8, 20, 21, 17, 55, 249388, tzinfo=timezone.utc)
    naive = instant.replace(tzinfo=None)
    assert ts(naive) == ts(instant) == "2026-08-20T21:17:55.249388Z"
    assert ts_offset(naive) == ts_offset(instant) == "2026-08-20T21:17:55.249388+00:00"


def test_aware_non_utc_is_converted(non_utc_host):
    plus_three = datetime(2026, 8, 21, 0, 17, 55, 249388,
                          tzinfo=timezone(timedelta(hours=3)))
    assert ts(plus_three) == "2026-08-20T21:17:55.249388Z"
    assert aware(plus_three).tzinfo == timezone.utc
