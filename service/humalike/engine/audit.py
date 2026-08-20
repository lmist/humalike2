"""Deterministic parsing and staged full-audit projections."""

from __future__ import annotations

import re

_TIMESTAMPED = re.compile(r"^\[\d\d:\d\d\]\s+(.+?): (.*)$")
_PLAIN = re.compile(r"^(.+?): (.*)$")
_AGENT_HINTS = ("bot", "agent", "assistant", "support")
_HIGH_RISK = ("hate", "idiot", "useless", "shut up")
_MEDIUM_RISK = (
    "broke",
    "broken",
    "fail",
    "again",
    "does not help",
    "doesn't help",
    "manually",
)


def estimated_tokens(raw_text: str) -> int:
    return (len(raw_text) * 401) // 1000


def parse_raw_text(raw_text: str) -> list[dict]:
    """Parse timestamped or plain ``Speaker: text`` lines."""
    parsed = []
    for line in raw_text.splitlines():
        match = _TIMESTAMPED.match(line) or _PLAIN.match(line)
        if match is None:
            continue
        speaker, text = match.groups()
        if not speaker:
            continue
        parsed.append({
            "id": f"m{len(parsed) + 1}",
            "speaker": speaker,
            "text": text,
            "user_id": None,
            "channel": None,
            "timestamp": None,
            "reply_to": None,
        })
    return parsed


def participants(messages: list[dict]) -> list[str]:
    return list(dict.fromkeys(message["speaker"] for message in messages))


def guess_agent(names: list[str]) -> str | None:
    for name in names:
        lowered = name.lower()
        if any(hint in lowered for hint in _AGENT_HINTS):
            return name
    if len(names) == 2:
        return names[1]
    return None


def _risk(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in _HIGH_RISK):
        return "high"
    if any(token in lowered for token in _MEDIUM_RISK):
        return "medium"
    return "low"


def build_read(messages: list[dict], agent_name: str) -> dict:
    humans = [name for name in participants(messages) if name != agent_name]
    agent_messages = [
        message["text"] for message in messages if message["speaker"] == agent_name
    ]
    return {
        "prompt_block": (
            f"Respond as {agent_name}; acknowledge unresolved issues and avoid repetition."
            if agent_name else None
        ),
        "portrait": {
            "role": "conversation agent",
            "personality": "direct and task-focused",
            "register": "plain",
        } if agent_name else None,
        "mental_state": [{
            "name": name,
            "beliefs": ["The conversation should address the stated issue."],
            "goals": ["Reach a useful resolution."],
            "emotions": [{
                "type": "frustration"
                if _risk(" ".join(
                    message["text"]
                    for message in messages
                    if message["speaker"] == name
                )) != "low"
                else "neutral",
                "intensity": 0.7
                if _risk(" ".join(
                    message["text"]
                    for message in messages
                    if message["speaker"] == name
                )) != "low"
                else 0.2,
            }],
        } for name in humans],
        "profiles": [{
            "name": name,
            "facts": [
                f"Contributed {sum(message['speaker'] == name for message in messages)} turn(s)."
            ],
        } for name in humans],
    }


def build_verdicts(messages: list[dict], agent_name: str) -> list[dict]:
    verdicts = []
    for index, message in enumerate(messages):
        if message["speaker"] != agent_name:
            continue
        following = next(
            (
                candidate["text"]
                for candidate in messages[index + 1:]
                if candidate["speaker"] != agent_name
            ),
            "The conversation may continue without a clear resolution.",
        )
        context = " ".join(
            candidate["text"] for candidate in messages[max(0, index - 1):index + 2]
        )
        risk = _risk(context)
        verdicts.append({
            "index": index,
            "risk": risk,
            "summary": (
                "This turn may leave the participant's issue unresolved."
                if risk != "low"
                else "This turn carries limited conversational risk."
            ),
            "predicted_message": following,
        })
    return verdicts


def build_replies(verdicts: list[dict]) -> list[dict]:
    replies = []
    for verdict in verdicts:
        bubble = (
            "I hear that this is still unresolved. I’ll address the specific issue "
            "and give you a concrete next step."
        )
        replies.append({
            "index": verdict["index"],
            "reply": bubble,
            "messages": [bubble],
            "risk": verdict["risk"],
        })
    return replies
