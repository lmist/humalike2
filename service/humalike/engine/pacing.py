"""Pacing engine (spec/03 §Reply refinement and scheduling).

typing_i  = min(max_typing_ms, max(500, words_i / typing_wpm * 60000))
deliver_0 = created_at_0 + reading_delay_ms + typing_0
deliver_i = deliver_{i-1} + 200 + typing_i        (i >= 1)

The 500 ms typing floor and the fixed 200 ms inter-bubble gap are mandatory;
max_typing_ms caps typing only and excludes the gap. Defaults are 0/150/8000.
"""

from __future__ import annotations

from datetime import datetime, timedelta

TYPING_FLOOR_MS = 500.0
INTER_BUBBLE_GAP_MS = 200.0
DEFAULT_READING_DELAY_MS = 0.0
DEFAULT_TYPING_WPM = 150.0
DEFAULT_MAX_TYPING_MS = 8000.0


def word_count(text: str) -> int:
    return len([w for w in text.strip().split() if w])


def resolve_pacing(pacing: dict | None) -> tuple[float, float, float]:
    """Apply defaults per member when pacing or any member is omitted."""
    pacing = pacing or {}
    reading_delay_ms = pacing.get("reading_delay_ms")
    typing_wpm = pacing.get("typing_wpm")
    max_typing_ms = pacing.get("max_typing_ms")
    return (
        float(reading_delay_ms) if reading_delay_ms is not None else DEFAULT_READING_DELAY_MS,
        float(typing_wpm) if typing_wpm is not None else DEFAULT_TYPING_WPM,
        float(max_typing_ms) if max_typing_ms is not None else DEFAULT_MAX_TYPING_MS,
    )


def typing_ms(words: int, typing_wpm: float, max_typing_ms: float) -> float:
    return min(max_typing_ms, max(TYPING_FLOOR_MS, words / typing_wpm * 60_000.0))


def deliver_times(
    bubbles: list[str],
    created_at_0: datetime,
    reading_delay_ms: float,
    typing_wpm: float,
    max_typing_ms: float,
) -> list[datetime]:
    times: list[datetime] = []
    for i, content in enumerate(bubbles):
        t = typing_ms(word_count(content), typing_wpm, max_typing_ms)
        if i == 0:
            deliver = created_at_0 + timedelta(milliseconds=reading_delay_ms + t)
        else:
            deliver = times[-1] + timedelta(milliseconds=INTER_BUBBLE_GAP_MS + t)
        times.append(deliver)
    return times
