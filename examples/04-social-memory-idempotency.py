#!/usr/bin/env python3
"""Phase 4 — Social Memory: ordered ingest, attribution, and owner-wide idempotency.

Ingests a short transcript, recalls it with subject attribution preserved,
asks a grounded question, and then exercises all three replay classes of an
``Idempotency-Key``: identical body, changed body, and a different
``scope_id``. All three must return the *first* response, and none may add
anything to memory (spec/02 §Idempotency and concurrency).

    HUMALIKE_API_URL=http://127.0.0.1:8191 HUMALIKE_API_KEY=ak_... \\
      python3 examples/04-social-memory-idempotency.py
"""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "clients", "python"))

from humalike_client import HumalikeClient  # noqa: E402

hum = HumalikeClient()

scope = f"example-04-{uuid.uuid4()}"
other_scope = f"example-04-other-{uuid.uuid4()}"
transcript = [
    {"speaker": "Ada", "text": "Grace just moved to Lisbon for the new lab."},
    {"speaker": "Grace", "text": "The lab runs on Tuesdays and Thursdays."},
    {"speaker": "Ada", "text": "I am allergic to shellfish, so no seafood place."},
]

ingested = hum.ingest(scope, transcript)
print(f"ingest        {ingested} x-request-id={hum.last_request_id}")
assert ingested["ingested"] == len(transcript), "ingested must equal the transcript length"

# Attribution is subject-centric: Ada stated where Grace lives, and recall must
# still attribute Lisbon to Grace rather than to the speaker.
recalled = hum.recall(scope, {"speaker": "Ada", "text": "Where does Grace live now?"})
print(f"recall        {recalled['context']!r}")
assert "Lisbon" in recalled["context"], "recall lost the attributed fact"

answer = hum.ask(scope, "Which days does the lab run?")
print(f"ask           {answer['answer']!r}")
assert "Tuesday" in answer["answer"], "ask must be grounded in ingested content"

# A fresh scope is empty, not an error.
empty = hum.recall(f"example-04-empty-{uuid.uuid4()}", {"speaker": "Ada", "text": "anything?"})
print(f"empty scope   {empty}")
assert empty == {"context": ""}, "a fresh scope returns exactly {context: ''}"

key = f"example-04-{uuid.uuid4()}"
first = hum.ingest(scope, [{"speaker": "Ada", "text": "We meet at the harbour cafe."}], key)
print(f"idempotent 1  {first} (first write)")

same_body = hum.ingest(scope, [{"speaker": "Ada", "text": "We meet at the harbour cafe."}], key)
changed_body = hum.ingest(scope, [
    {"speaker": "Ada", "text": "Actually the harbour cafe is closed."},
    {"speaker": "Grace", "text": "Then the library it is."},
], key)
other = hum.ingest(other_scope, [{"speaker": "Grace", "text": "This must not be stored."}], key)
print(f"idempotent 2  same_body={same_body} changed_body={changed_body} other_scope={other}")
assert same_body == changed_body == other == first, \
    "every replay of an (owner,key) returns the first response"

# The changed body was silently ignored, and the other scope stored nothing.
after = hum.ask(scope, "Is the harbour cafe closed?")
assert "closed" not in after["answer"], "a replayed changed body must not reach memory"
elsewhere = hum.recall(other_scope, {"speaker": "Grace", "text": "what was stored here?"})
print(f"other scope   {elsewhere}")
assert elsewhere == {"context": ""}, "a replay under a different scope stores nothing there"

print("04-social-memory-idempotency OK")
