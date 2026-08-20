"""Theory-of-Mind refinement stage (spec/05 §Refinement, splitting, and pacing).

Consumes transcript context, recalled memory, learned profile, system prompt,
agent identity, and the draft; produces modeled mental state, a refined
reply, and a rationale. Exact prose is not a conformance claim; required
facts and intent MUST remain grounded, so this deterministic substitute
preserves the draft content verbatim (the naturalizer handles splitting)
while modeling participant state for the internal trace. Real model-backed
refinement is a configuration concern (ADR hum-vdio).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Refinement:
    refined: str
    mental_state: list[dict] = field(default_factory=list)
    rationale: str = ""


def refine(
    draft: str,
    transcript: list[dict] | None = None,
    recalled_context: str = "",
    system_prompt: str | None = None,
    agent_name: str | None = None,
) -> Refinement:
    """Model recipients and refine the draft, preserving every draft fact."""
    speakers: list[str] = []
    for message in transcript or []:
        sender = message.get("sender") or message.get("speaker")
        if sender and sender != agent_name and sender not in speakers:
            speakers.append(sender)
    mental_state = [
        {
            "name": speaker,
            "beliefs": [f"{speaker} expects a direct, complete reply."],
            "goals": [f"{speaker} wants their last message addressed."],
            "emotions": [{"type": "anticipation", "intensity": 0.5}],
        }
        for speaker in speakers
    ]
    rationale = (
        "Draft preserved verbatim: deterministic refinement keeps required "
        "facts and intent grounded; pacing and splitting are applied by the "
        "naturalizer."
    )
    return Refinement(refined=draft, mental_state=mental_state, rationale=rationale)
