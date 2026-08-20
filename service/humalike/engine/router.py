"""HUMA-style turn router (spec/05 §Turn router and interruption).

Production's exact model, prompts, and strategy catalog are not public
(ADR hum-7tqi); this deterministic substitute scores a small strategy set
(Directly Mentioned, Keep Silent, Continue Pending) and must be capable of
both speak and stay_silent. skip_decide and media short-circuit to speak
without modeled decision work at the call site, not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Decision:
    decision: str  # "speak" | "stay_silent"
    scores: dict[str, float]


_NAME_PATTERNS = (
    re.compile(r"[Yy]ou are (?:the )?([A-Z][\w'-]*(?: [A-Z][\w'-]*)*)"),
    re.compile(r"address(?:es|ed)? ([A-Z][\w'-]*(?: [A-Z][\w'-]*)*)"),
)

_ACK_WORD = r"(?:ok(?:ay)?|thanks?|thank you|lol|nice|cool|got it|sure|yep|yes|no|k)"
_ACK_RE = re.compile(rf"^(?:{_ACK_WORD}[.,! ]*){{1,3}}$", re.IGNORECASE)


def agent_names(system_prompt: str | None, agent_name: str | None = None) -> list[str]:
    names: list[str] = []
    if agent_name:
        names.append(agent_name)
    if system_prompt:
        for pattern in _NAME_PATTERNS:
            m = pattern.search(system_prompt)
            if m:
                names.append(m.group(1).strip())
    return names


def _mentions(content: str, names: list[str]) -> bool:
    lowered = content.lower()
    return any(name and name.lower() in lowered for name in names)


def _addresses_other(content: str, names: list[str]) -> bool:
    """A leading vocative ("Bob, ...") or @-mention naming someone else."""
    m = re.match(r"^\s*@?([A-Z][\w'-]*(?:[ -][A-Z][\w'-]*)?)\s*[,:]", content)
    if m and not _mentions(m.group(1), names):
        return True
    if re.search(r"@[\w-]+", content) and not _mentions(content, names):
        return True
    return False


def decide(messages: list[dict], system_prompt: str | None) -> Decision:
    """Deterministic speak/stay_silent decision over the accepted batch."""
    names = agent_names(system_prompt)
    scores = {"directly_mentioned": 0.0, "keep_silent": 0.1, "continue_pending": 0.2}
    for message in messages:
        content = message.get("content", "")
        if names and _mentions(content, names):
            scores["directly_mentioned"] = 1.0
        if _ACK_RE.match(content.strip()):
            scores["keep_silent"] = max(scores["keep_silent"], 0.9)
        if _addresses_other(content, names):
            scores["keep_silent"] = max(scores["keep_silent"], 0.8)
    if scores["directly_mentioned"] >= 1.0:
        return Decision("speak", scores)
    if names and scores["keep_silent"] >= 0.8:
        # An engineered lurker prompt with traffic addressed to others.
        return Decision("stay_silent", scores)
    return Decision("speak", scores)
