#!/usr/bin/env python3
"""Phase 5 — Theory of Mind: model a named subject and refine a draft reply.

With ``subject_name`` supplied, both ``mental_state`` and ``predicted_reaction``
must contain exactly one entry named for that subject. Emotion intensities lie
in [0,1] and every predicted reaction carries a low/medium/high risk.

Also shows the alias trap: ``conversation``/``draft`` are not accepted, and
sending them returns 422 naming ``transcript`` and ``candidate_reply`` as
``missing``.

    HUMALIKE_API_URL=http://127.0.0.1:8191 HUMALIKE_API_KEY=ak_... \\
      python3 examples/06-foresee.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "clients", "python"))

from humalike_client import HumalikeApiError, HumalikeClient  # noqa: E402

hum = HumalikeClient()

transcript = [
    {"speaker": "Lin", "text": "I stayed up rewriting the deck you asked for."},
    {"speaker": "Lin", "text": "Is there any chance we can move the review?"},
    {"speaker": "Grace", "text": "The client already confirmed the slot."},
]
draft = "No, we can't move it. You had a week for this."

result = hum.foresee(
    transcript=transcript,
    candidate_reply=draft,
    agent_name="Grace",
    subject_name="Lin",
)
print(f"foresee       x-request-id={hum.last_request_id}")

assert len(result["mental_state"]) == 1, "subject_name must narrow mental_state to one entry"
assert len(result["predicted_reaction"]) == 1, "subject_name must narrow predicted_reaction to one entry"
assert result["mental_state"][0]["name"] == "Lin"
assert result["predicted_reaction"][0]["name"] == "Lin"

state = result["mental_state"][0]
print(f"mental_state  name={state['name']!r}")
for belief in state["beliefs"]:
    print(f"  belief      {belief!r}")
for goal in state["goals"]:
    print(f"  goal        {goal!r}")
for emotion in state["emotions"]:
    assert 0.0 <= emotion["intensity"] <= 1.0, "emotion intensity must lie in [0,1]"
    print(f"  emotion     {emotion['type']!r} intensity={emotion['intensity']}")

reaction = result["predicted_reaction"][0]
assert reaction["risk"] in ("low", "medium", "high")
print(f"reaction      risk={reaction['risk']} summary={reaction['summary']!r}")
print(f"predicted     {reaction['predicted_message']!r}")
print(f"refined       {result['refined_reply']!r}")
print(f"rationale     {result['refinement_rationale']!r}")

# The aliases a caller reaches for first are rejected on purpose.
try:
    hum.request("POST", "/v1/foresee/actions/foresee",
                {"conversation": transcript, "draft": draft})
    raise SystemExit("conversation/draft must not be accepted as aliases")
except HumalikeApiError as exc:
    assert exc.status == 422, f"expected 422, got {exc.status}"
    missing = sorted(d["loc"][-1] for d in exc.body["error"]["details"])
    print(f"aliases       422 missing={missing}")

print("06-foresee OK")
