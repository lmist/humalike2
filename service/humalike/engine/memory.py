"""Social Memory engine (spec/05 §Social Memory).

Raw messages are stored in owner/scope order. Facts are subject-centric with
evidence links and contradiction metadata. Recall and Ask use deterministic
entity/speaker-aware lexical retrieval (ADR hum-a667: vector storage stays a
configuration option) that preserves tested subject attribution and
transcript ordering while allowing paraphrase.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select

from ..db import session
from ..storage import MemoryFact, MemoryMessage
from ..timefmt import utcnow

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "of", "to",
    "and", "or", "in", "on", "at", "for", "with", "my", "your", "our", "their",
    "his", "her", "its", "me", "you", "i", "we", "they", "he", "she", "it",
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
    "do", "does", "did", "please", "remind", "tell", "am", "this", "that",
}

_SUBJECT_RE = re.compile(r"\b(?:person )?([A-Z][\w'-]+)(?:'s)?\b")


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[\w'-]+", text.lower())
    out = set()
    for w in words:
        w = w.strip("'-")
        if not w or w in _STOPWORDS:
            continue
        out.add(w)
        # Light stemming so "works" matches "work" and "codes" matches "code".
        if len(w) > 3 and w.endswith("s"):
            out.add(w[:-1])
    return out


def _subjects(speaker: str, text: str) -> list[str]:
    """Subject-centric attribution: named entities in the text, else speaker."""
    names = [m.group(1) for m in _SUBJECT_RE.finditer(text)]
    return names or [speaker]


def ingest(owner_id: str, scope_id: str, transcript: list[dict]) -> int:
    """Append the ordered transcript; extract facts with evidence links."""
    now = utcnow()
    with session() as s:
        start = s.execute(
            select(func.coalesce(func.max(MemoryMessage.seq), -1))
            .where(MemoryMessage.owner_id == owner_id,
                   MemoryMessage.scope_id == scope_id)
        ).scalar_one() + 1
        existing_facts = s.execute(
            select(MemoryFact).where(MemoryFact.owner_id == owner_id,
                                     MemoryFact.scope_id == scope_id)
        ).scalars().all()
        by_subject: dict[str, MemoryFact] = {f.subject.lower(): f for f in existing_facts}
        for offset, message in enumerate(transcript):
            seq = start + offset
            speaker = message["speaker"]
            text = message["text"]
            s.add(MemoryMessage(owner_id=owner_id, scope_id=scope_id, seq=seq,
                                speaker=speaker, text=text, created_at=now))
            for subject in _subjects(speaker, text):
                prior = by_subject.get(subject.lower())
                fact = MemoryFact(
                    owner_id=owner_id, scope_id=scope_id, subject=subject,
                    speaker=speaker, text=text, evidence_seq=seq,
                    contradicts_id=prior.id if prior is not None and prior.text != text else None,
                    created_at=now,
                )
                s.add(fact)
                s.flush()
                by_subject[subject.lower()] = fact
    return len(transcript)


def _retrieve(owner_id: str, scope_id: str, query: str, speaker: str | None = None,
              limit: int = 6) -> list[MemoryMessage]:
    """Lexical retrieval in transcript order, entity/speaker aware."""
    query_tokens = _tokens(query)
    if speaker:
        query_tokens |= _tokens(speaker)
    with session() as s:
        rows = s.execute(
            select(MemoryMessage)
            .where(MemoryMessage.owner_id == owner_id,
                   MemoryMessage.scope_id == scope_id)
            .order_by(MemoryMessage.seq)
        ).scalars().all()
    scored: list[tuple[float, MemoryMessage]] = []
    for row in rows:
        row_tokens = _tokens(row.text) | _tokens(row.speaker)
        overlap = len(query_tokens & row_tokens)
        if overlap > 0:
            scored.append((overlap, row))
    if not scored:
        return []
    scored.sort(key=lambda pair: (-pair[0], pair[1].seq))
    picked = {id(row) for _, row in scored[:limit]}
    return [row for _, row in sorted(
        ((score, row) for score, row in scored if id(row) in picked),
        key=lambda pair: pair[1].seq,
    )]


def recall(owner_id: str, scope_id: str, speaker: str, text: str) -> str:
    """Concise context preserving subject attribution; "" for a fresh scope."""
    matches = _retrieve(owner_id, scope_id, text, speaker=speaker)
    if not matches:
        return ""
    lines = [f"{row.speaker}: {row.text}" for row in matches]
    return "\n".join(lines)


def ask(owner_id: str, scope_id: str, question: str) -> str:
    """Direct grounded answer preserving tested ordering facts."""
    matches = _retrieve(owner_id, scope_id, question)
    if not matches:
        return "No stored memory answers that question."
    return " ".join(row.text for row in matches)
