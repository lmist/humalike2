"""Naturalizer: bounded 1-5 bubble split, merge-not-truncate (spec/05).

The split heuristic is model-driven in production and not a conformance
claim (ADR hum-tisv). This deterministic substitute splits a draft on blank
lines (paragraph boundaries) and merges down to at most five bubbles with
every character of content preserved, never truncated. It satisfies the
model-dependent gates: a multi-paragraph "send separately" draft yields 2-5
bubbles and a six-paragraph draft merges to at most five with all seed
tokens surviving verbatim.
"""

from __future__ import annotations

import re

MAX_BUBBLES = 5


def split_paragraphs(draft: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", draft) if p.strip()]
    if not parts:
        stripped = draft.strip()
        return [stripped] if stripped else []
    return parts


def merge_down(parts: list[str], limit: int = MAX_BUBBLES) -> list[str]:
    """Merge adjacent bubbles until at most `limit` remain; nothing is lost."""
    merged = list(parts)
    while len(merged) > limit:
        # Merge the pair whose combined length is smallest to keep bubbles even.
        best = min(range(len(merged) - 1), key=lambda i: len(merged[i]) + len(merged[i + 1]))
        merged[best:best + 2] = [merged[best] + "\n" + merged[best + 1]]
    return merged


def naturalize(draft: str) -> list[str]:
    """Return 1-5 non-empty bubbles preserving all draft content."""
    parts = split_paragraphs(draft)
    if not parts:
        return []
    return merge_down(parts, MAX_BUBBLES)
