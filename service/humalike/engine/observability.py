"""Deterministic Social Observability report construction."""

from __future__ import annotations

from collections import Counter
from typing import Literal


INTERACTION_TYPES = (
    "transactional",
    "bonding",
    "venting",
    "banter",
    "friction",
    "hostile",
)

_HOSTILE = ("idiot", "stupid", "hate you", "shut up", "useless")
_FRICTION = (
    "broke",
    "broken",
    "fail",
    "again",
    "does not help",
    "doesn't help",
    "same answer",
    "retry later",
    "nevermind",
    "never mind",
)
_VENTING = ("frustrat", "annoy", "ugh", "fed up", "tired of")
_BANTER = ("lol", "haha", "joke", "😂")
_BONDING = ("thank", "thanks", "bless", "appreciate", "gotchu")


def _interaction_type(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in _HOSTILE):
        return "hostile"
    if any(token in lowered for token in _FRICTION):
        return "friction"
    if any(token in lowered for token in _VENTING):
        return "venting"
    if any(token in lowered for token in _BANTER):
        return "banter"
    if any(token in lowered for token in _BONDING):
        return "bonding"
    return "transactional"


def _unique_speakers(messages: list[dict]) -> list[str]:
    return list(dict.fromkeys(message["speaker"] for message in messages))


def _user_ids(messages: list[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for message in messages:
        user_id = message.get("user_id")
        if user_id is not None and message["speaker"] not in result:
            result[message["speaker"]] = user_id
    return result


def build_report(
    messages: list[dict],
    agent_name: str,
    focus: str | None = None,
    *,
    user_id_mode: Literal["echo", "null"] = "echo",
) -> dict:
    """Build a stable report whose aggregate fields derive from interactions."""
    speakers = _unique_speakers(messages)
    ids_by_speaker = {
        speaker: [message["id"] for message in messages if message["speaker"] == speaker]
        for speaker in speakers
    }
    user_ids = _user_ids(messages)

    interactions = []
    for start in range(0, len(messages), 2):
        window = messages[start:start + 2]
        text = " ".join(message["text"] for message in window)
        names = list(dict.fromkeys(message["speaker"] for message in window))
        participants = []
        for name in names:
            participant = {"name": name, "stance": "contributor"}
            if user_id_mode == "echo" and name in user_ids:
                participant["user_id"] = user_ids[name]
            participants.append(participant)
        topic = next(
            (message["text"].strip() for message in window if message["text"].strip()),
            "Conversation exchange",
        )
        interactions.append({
            "type": _interaction_type(text),
            "topic": topic[:160],
            "participants": participants,
            "message_ids": [message["id"] for message in window],
        })

    total_counts = Counter(interaction["type"] for interaction in interactions)
    interaction_totals = [
        {"type": interaction_type, "count": total_counts[interaction_type]}
        for interaction_type in INTERACTION_TYPES
    ]

    per_user = []
    for speaker in speakers:
        participated = [
            interaction
            for interaction in interactions
            if any(participant["name"] == speaker for participant in interaction["participants"])
        ]
        distribution_counts = Counter(item["type"] for item in participated)
        dominant_type = max(
            INTERACTION_TYPES,
            key=lambda interaction_type: (
                distribution_counts[interaction_type],
                -INTERACTION_TYPES.index(interaction_type),
            ),
        )
        speaker_text = " ".join(
            message["text"].lower()
            for message in messages
            if message["speaker"] == speaker
        )
        negative = any(token in speaker_text for token in _HOSTILE + _FRICTION + _VENTING)
        evidence = ids_by_speaker[speaker]
        user = {
            "name": speaker,
            "reception": "annoyed" if negative else "engaged",
            "frustration": 0.72 if negative else 0.18,
            "trend": "declining" if negative else "stable",
            "behaviors": [f"Participates in {len(participated)} interaction(s)"],
            "evidence": evidence,
            "confidence": 0.78,
            "interaction_count": len(participated),
            "dominant_type": dominant_type,
            "distribution": [
                {"type": interaction_type, "count": distribution_counts[interaction_type]}
                for interaction_type in INTERACTION_TYPES
            ],
            "key_moments": [{
                "label": "Representative turn",
                "type": dominant_type,
                "message_ids": evidence[:1],
            }],
        }
        if user_id_mode == "null":
            user["user_id"] = None
        elif speaker in user_ids:
            user["user_id"] = user_ids[speaker]
        per_user.append(user)

    friction_count = sum(
        total_counts[kind] for kind in ("friction", "hostile", "venting")
    )
    health_score = round(max(0.0, 1.0 - friction_count / max(1, len(interactions))), 2)
    subject = focus.strip() if focus and focus.strip() else "the observed conversation"
    summary = (
        f"Deterministic analysis of {subject}: {len(interactions)} interaction(s) "
        f"across {len(speakers)} participant(s), with {agent_name} as the named agent."
    )
    return {
        "health_score": health_score,
        "summary": summary,
        "interactions": interactions,
        "interaction_totals": interaction_totals,
        "per_user": per_user,
        "findings": [],
    }
