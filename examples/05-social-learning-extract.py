#!/usr/bin/env python3
"""Phase 5 — Social Learning: extract a style profile and a prompt block.

Sends a small labelled transcript and checks the invariants that hold
regardless of which model wrote the prose: the echoed ``source``, the exact
message count, every ``confidence`` inside [0,1], and a non-empty
``prompt_block``.

``meta.channels`` is deliberately *not* asserted: it is model-authored, and a
channel-less transcript has produced both ``[]`` and ``["general"]`` live
(spec/08 open question 8).

    HUMALIKE_API_URL=http://127.0.0.1:8191 HUMALIKE_API_KEY=ak_... \\
      python3 examples/05-social-learning-extract.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "clients", "python"))

from humalike_client import HumalikeClient  # noqa: E402

hum = HumalikeClient()

transcript = {
    "source": "example-05",
    "messages": [
        {"id": "m1", "speaker": "Ada", "text": "morning all — standup in 5?", "channel": "team"},
        {"id": "m2", "speaker": "Grace", "text": "yep, joining", "channel": "team"},
        {"id": "m3", "speaker": "Ada", "text": "we don't @ people before 9am here, fyi", "channel": "team"},
        {"id": "m4", "speaker": "Lin", "text": "noted, sorry!"},
        {"id": "m5", "speaker": "Ada", "text": "no stress. ship it 🚀", "channel": "team"},
    ],
}

extracted = hum.extract(transcript)
profile = extracted["profile"]
print(f"extract       x-request-id={hum.last_request_id}")
print(f"meta          source={profile['meta']['source']!r} "
      f"message_count={profile['meta']['message_count']} "
      f"channels={profile['meta']['channels']}")

assert profile["meta"]["source"] == "example-05", "meta.source must echo the request source"
assert profile["meta"]["message_count"] == len(transcript["messages"]), \
    "meta.message_count must equal the input length"
assert extracted["prompt_block"], "prompt_block must be non-empty"

confidences = [profile["register"]["confidence"]] + [n["confidence"] for n in profile["norms"]]
assert all(0.0 <= c <= 1.0 for c in confidences), f"confidence out of [0,1]: {confidences}"

print(f"register      formality={profile['register']['formality']!r} "
      f"warmth={profile['register']['warmth']!r} casing={profile['register']['casing']!r} "
      f"confidence={profile['register']['confidence']}")
print(f"style         {json.dumps(profile['style'])}")
for norm in profile["norms"]:
    print(f"  norm        {norm['rule']!r} type={norm['type']!r} confidence={norm['confidence']}")
for taboo in profile["taboos"]:
    print(f"  taboo       {taboo['rule']!r} scope={taboo['scope']!r} evidence={taboo['evidence']}")
print(f"prompt_block  {len(extracted['prompt_block'])} characters")

# Learned style is refreshed independently from durable factual memory: nothing
# here is written to a Social Memory scope (spec/04 §Social Learning).
print("05-social-learning-extract OK")
