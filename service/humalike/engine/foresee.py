"""Theory-of-Mind foresee engine (spec/04 §Theory of Mind).

Deterministic mental-state and reaction modeling. Beliefs and goals are
grounded in the subject's own transcript turns. The refined reply
acknowledges the subject's last unresolved statement, then carries the
candidate reply forward.
"""

from __future__ import annotations

import re


_NEGATIVE = (
    "fail", "failed", "error", "broken", "already", "never", "wrong",
    "manually", "again", "still", "frustrated", "angry", "issue",
)
_POSITIVE = ("thanks", "great", "nice", "love", "perfect", "awesome", "good")
_DISMISSIVE = (
    "anything else", "reach out if", "let me know if", "if you need",
    "no problem", "you're welcome",
)
_GOAL_RE = re.compile(
    r"\b(?:i will|i'll|i am going to|i need|i want|let me|just)\b(.+)",
    re.IGNORECASE,
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _speakers_in_order(transcript: list[dict]) -> list[str]:
    seen: list[str] = []
    for turn in transcript:
        name = turn.get("speaker") or ""
        if name and name not in seen:
            seen.append(name)
    return seen


def subject_names(
    transcript: list[dict],
    agent_name: str | None,
    subject_name: str | None,
) -> list[str]:
    """With subject_name: exactly that name. Else each non-agent speaker."""
    if subject_name:
        return [subject_name]
    names = [
        name for name in _speakers_in_order(transcript)
        if not agent_name or name != agent_name
    ]
    return names or _speakers_in_order(transcript)


def _texts_for(transcript: list[dict], name: str) -> list[str]:
    return [
        turn.get("text") or ""
        for turn in transcript
        if (turn.get("speaker") or "") == name and (turn.get("text") or "")
    ]


def _beliefs(name: str, texts: list[str]) -> list[str]:
    return [f'{name} said: "{text}"' for text in texts]


def _goals(name: str, texts: list[str]) -> list[str]:
    goals: list[str] = []
    for text in texts:
        match = _GOAL_RE.search(text)
        if match:
            fragment = match.group(0).strip()
            goals.append(f"{name} intends to {fragment}")
        if "?" in text:
            goals.append(f"{name} wants a resolution to: {text}")
    if not goals and texts:
        goals.append(f"{name} wants the situation in \"{texts[-1]}\" resolved")
    return goals


def _emotions(texts: list[str]) -> list[dict]:
    blob = " ".join(texts).lower()
    score = 0.0
    kind = "neutral"
    for token in _NEGATIVE:
        if token in blob:
            score += 0.18
            kind = "frustrated"
    if "already" in blob or "manually" in blob:
        kind = "resigned" if kind == "frustrated" else kind
        score += 0.12
    for token in _POSITIVE:
        if token in blob:
            score += 0.08
            if kind == "neutral":
                kind = "positive"
    if "!" in blob:
        score += 0.08
    intensity = _clamp01(0.25 + score)
    if kind == "neutral":
        intensity = _clamp01(0.2 + 0.05 * min(len(texts), 4))
    return [{"type": kind, "intensity": round(intensity, 3)}]


def _unresolved(texts: list[str]) -> bool:
    blob = " ".join(texts).lower()
    return any(token in blob for token in (
        "fail", "error", "already", "broken", "not work", "manually", "issue",
    ))


def _dismissive(candidate: str) -> bool:
    lowered = candidate.lower()
    return any(token in lowered for token in _DISMISSIVE)


def _risk(texts: list[str], candidate: str) -> str:
    if _unresolved(texts) and _dismissive(candidate):
        return "high"
    if _unresolved(texts):
        return "medium"
    return "low"


def _reaction(name: str, texts: list[str], candidate: str) -> dict:
    last = texts[-1] if texts else ""
    risk = _risk(texts, candidate)
    if risk == "high":
        summary = (
            f"{name} has an unresolved issue and is likely to read a "
            f"close-out as dismissal of \"{last}\""
        )
        predicted = (
            f"I already explained this. I will just handle it myself."
            if last else
            f"{name} will disengage."
        )
    elif risk == "medium":
        summary = f"{name} still needs a resolution around \"{last}\""
        predicted = f"Can we actually fix this? {last}"
    else:
        summary = f"{name} is likely to accept the reply"
        predicted = "Okay, thanks."
    return {
        "name": name,
        "summary": summary,
        "predicted_message": predicted,
        "risk": risk,
    }


def _refined_reply(
    subjects: list[str],
    transcript: list[dict],
    candidate_reply: str,
    system_prompt: str | None,
) -> tuple[str, str]:
    last_unresolved = ""
    last_name = subjects[0] if subjects else ""
    for name in subjects:
        texts = _texts_for(transcript, name)
        if texts:
            last_unresolved = texts[-1]
            last_name = name
    prompt_note = ""
    if system_prompt:
        prompt_note = f" Following: {system_prompt.rstrip('.')}."
    if last_unresolved:
        refined = (
            f"I hear you — {last_name} said \"{last_unresolved}\". "
            f"{candidate_reply}".strip()
        )
        rationale = (
            f"Acknowledged {last_name}'s last statement "
            f"(\"{last_unresolved}\") before carrying the candidate reply "
            f"forward so the unresolved point stays on the table.{prompt_note}"
        )
    else:
        refined = candidate_reply.strip() or "Understood."
        rationale = (
            f"No unresolved subject statement was found; the candidate "
            f"reply is returned with a brief rationale.{prompt_note}"
        )
    if not refined:
        refined = "Understood."
    return refined, rationale


def foresee(
    transcript: list[dict],
    candidate_reply: str,
    agent_name: str | None = None,
    system_prompt: str | None = None,
    subject_name: str | None = None,
) -> dict:
    names = subject_names(transcript, agent_name, subject_name)
    mental_state = []
    predicted_reaction = []
    for name in names:
        texts = _texts_for(transcript, name)
        mental_state.append({
            "name": name,
            "beliefs": _beliefs(name, texts),
            "goals": _goals(name, texts),
            "emotions": _emotions(texts),
        })
        predicted_reaction.append(_reaction(name, texts, candidate_reply))
    refined_reply, rationale = _refined_reply(
        names, transcript, candidate_reply, system_prompt)
    return {
        "mental_state": mental_state,
        "predicted_reaction": predicted_reaction,
        "refined_reply": refined_reply,
        "refinement_rationale": rationale,
    }
