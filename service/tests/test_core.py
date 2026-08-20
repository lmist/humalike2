"""Deterministic unit tests for the core engine and protocol helpers.

Acceptance is live conformance *plus* deterministic internal tests (spec/07
§Delivery discipline). The live suites own the wire contract; this file owns
the pieces they can only observe indirectly: timestamp formatting, the
route-specific error serializers, the pacing arithmetic, merge-not-truncate
splitting, grant signing and expiry, the turn router's two outcomes, and
Social Memory retrieval.

Phases covered: 0 (serialization and error shapes), 2 (grants), 3 (pacing,
naturalizer, router), 4 (memory retrieval and idempotency).
"""

from __future__ import annotations

import atexit
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Bind a scratch database before anything imports humalike.config: the engine
# is built at import time from HUMALIKE_DATABASE_URL, and a test run must never
# touch a development or deployed database. One file per pytest process, so the
# three delivery-discipline test modules share it and separate runs do not.
_SCRATCH_DB = Path(tempfile.gettempdir()) / f"humalike-delivery-tests-{os.getpid()}.db"
os.environ["HUMALIKE_DATABASE_URL"] = f"sqlite:///{_SCRATCH_DB}"
os.environ.setdefault("HUMALIKE_SECRET", "delivery-discipline-test-secret")


@atexit.register
def _remove_scratch_db() -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(_SCRATCH_DB) + suffix).unlink(missing_ok=True)


from fastapi.exceptions import RequestValidationError  # noqa: E402

from humalike import errors, grants  # noqa: E402
from humalike.config import settings  # noqa: E402
from humalike.db import create_all  # noqa: E402
from humalike.engine import memory as memory_engine  # noqa: E402
from humalike.engine import router as turn_router  # noqa: E402
from humalike.engine.naturalizer import merge_down, naturalize, split_paragraphs  # noqa: E402
from humalike.engine.pacing import (  # noqa: E402
    DEFAULT_MAX_TYPING_MS,
    DEFAULT_READING_DELAY_MS,
    DEFAULT_TYPING_WPM,
    INTER_BUBBLE_GAP_MS,
    TYPING_FLOOR_MS,
    deliver_times,
    resolve_pacing,
    typing_ms,
    word_count,
)
from humalike.timefmt import now_ts, ts, ts_offset, utcnow  # noqa: E402

create_all()


def body_of(response) -> dict:
    return json.loads(response.body)


# ---------------------------------------------------------------------------
# Phase 0 — timestamp serialization (spec/02 §HTTP and serialization)
# ---------------------------------------------------------------------------

TS_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
TS_OFFSET_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$")


def test_ts_is_microsecond_precision_with_literal_z():
    assert TS_PATTERN.match(ts(datetime(2026, 8, 20, 19, 5, 3, 123456, tzinfo=timezone.utc)))
    assert ts(datetime(2026, 8, 20, 19, 5, 3, 123456, tzinfo=timezone.utc)) == \
        "2026-08-20T19:05:03.123456Z"


def test_ts_pads_microseconds_rather_than_truncating():
    # A whole-second timestamp still serializes six fractional digits; dropping
    # them would produce a string the suites reject.
    assert ts(datetime(2026, 1, 2, 3, 4, 5, 0, tzinfo=timezone.utc)) == "2026-01-02T03:04:05.000000Z"
    assert ts(datetime(2026, 1, 2, 3, 4, 5, 7, tzinfo=timezone.utc)) == "2026-01-02T03:04:05.000007Z"


def test_ts_converts_a_non_utc_instant_rather_than_relabelling_it():
    aware = datetime(2026, 8, 20, 21, 5, 3, 500000, tzinfo=timezone(timedelta(hours=2)))
    assert ts(aware) == "2026-08-20T19:05:03.500000Z"


def test_attached_server_time_uses_the_offset_form():
    # The sole exception to the literal Z rule (spec/03 §WebSocket frames).
    assert TS_OFFSET_PATTERN.match(ts_offset(utcnow()))
    assert not TS_PATTERN.match(ts_offset(utcnow()))


def test_now_ts_matches_the_http_timestamp_form():
    assert TS_PATTERN.match(now_ts())


# ---------------------------------------------------------------------------
# Phase 0-1 — route-specific error serializers (spec/02 §Error shapes)
# ---------------------------------------------------------------------------


def test_error_envelope_has_exactly_one_key():
    payload = errors.error_body("VALIDATION_ERROR", "invalid id")
    assert list(payload) == ["error"]
    assert payload == {"error": {"code": "VALIDATION_ERROR", "message": "invalid id"}}


def test_unauthorized_body_is_exact():
    response = errors.unauthorized()
    assert response.status_code == 401
    assert body_of(response) == {
        "error": {"code": "UNAUTHORIZED", "message": "missing or invalid credentials"}}


def test_payment_required_is_the_documented_default():
    response = errors.payment_required()
    assert response.status_code == 402
    assert body_of(response) == {
        "error": {"code": "PAYMENT_REQUIRED", "message": "insufficient credits"}}


def test_forbidden_uses_the_documented_lowercase_code():
    response = errors.forbidden()
    assert response.status_code == 403
    assert body_of(response)["error"]["code"] == "forbidden"


def test_upstream_error_uses_the_documented_code():
    response = errors.upstream_error()
    assert response.status_code == 502
    assert body_of(response)["error"]["code"] == "UPSTREAM_ERROR"


def test_invalid_id_carries_no_details_key():
    response = errors.invalid_id()
    assert response.status_code == 400
    assert body_of(response) == {
        "error": {"code": "VALIDATION_ERROR", "message": "invalid id"}}
    assert "details" not in body_of(response)["error"]


def test_semantic_validation_error_carries_field_details():
    response = errors.semantic_validation_error(
        "agent_name must be one of the transcript's speakers",
        [{"field": "agent_name", "message": "'Nobody' never speaks"}])
    assert response.status_code == 400
    assert body_of(response) == {"error": {
        "code": "VALIDATION_ERROR",
        "message": "agent_name must be one of the transcript's speakers",
        "details": [{"field": "agent_name", "message": "'Nobody' never speaks"}]}}


def test_request_validation_strips_the_leading_body_segment():
    # A stock FastAPI/Pydantic serializer emits loc[0] == "body" and fails the
    # suites; the recreation must not.
    exc = RequestValidationError([
        {"loc": ("body", "thread_id"), "msg": "invalid UUID", "type": "uuid_parsing"},
        {"loc": ("body", "transcript", "messages", 0, "id"), "msg": "field required", "type": "missing"},
    ])
    response = errors.validation_exception_handler(None, exc)
    assert response.status_code == 422
    payload = body_of(response)
    assert payload["error"]["code"] == "validation_failed"
    assert payload["error"]["message"] == "request validation failed"
    assert [d["loc"] for d in payload["error"]["details"]] == [
        ["thread_id"], ["transcript", "messages", 0, "id"]]
    assert [d["type"] for d in payload["error"]["details"]] == ["uuid_parsing", "missing"]


def test_request_validation_keeps_a_loc_that_never_had_a_body_prefix():
    exc = RequestValidationError([{"loc": ("question",), "msg": "too short", "type": "string_too_short"}])
    payload = body_of(errors.validation_exception_handler(None, exc))
    assert payload["error"]["details"][0]["loc"] == ["question"]


# ---------------------------------------------------------------------------
# Phase 3 — pacing math (spec/03 §Reply refinement and scheduling)
# ---------------------------------------------------------------------------


def test_pacing_defaults_are_zero_one_fifty_eight_thousand():
    assert resolve_pacing(None) == (0.0, 150.0, 8000.0)
    assert (DEFAULT_READING_DELAY_MS, DEFAULT_TYPING_WPM, DEFAULT_MAX_TYPING_MS) == (0.0, 150.0, 8000.0)


@pytest.mark.parametrize("pacing, expected", [
    ({}, (0.0, 150.0, 8000.0)),
    ({"reading_delay_ms": 250}, (250.0, 150.0, 8000.0)),
    ({"typing_wpm": 40}, (0.0, 40.0, 8000.0)),
    ({"max_typing_ms": 900}, (0.0, 150.0, 900.0)),
    ({"reading_delay_ms": None, "typing_wpm": None, "max_typing_ms": None}, (0.0, 150.0, 8000.0)),
])
def test_each_omitted_pacing_member_falls_back_independently(pacing, expected):
    assert resolve_pacing(pacing) == expected


def test_typing_time_has_a_five_hundred_millisecond_floor():
    assert typing_ms(0, 150.0, 8000.0) == TYPING_FLOOR_MS
    assert typing_ms(1, 150.0, 8000.0) == TYPING_FLOOR_MS  # 400 ms raw, floored


def test_typing_time_is_capped_by_max_typing_ms():
    assert typing_ms(10_000, 150.0, 8000.0) == 8000.0
    assert typing_ms(10_000, 150.0, 900.0) == 900.0


def test_typing_time_between_the_floor_and_the_cap_is_the_raw_formula():
    assert typing_ms(10, 150.0, 8000.0) == pytest.approx(10 / 150 * 60_000)


def test_word_count_ignores_repeated_whitespace():
    assert word_count("  two   words \n") == 2
    assert word_count("") == 0


def test_delivery_times_follow_the_formula_with_the_gap_outside_the_cap():
    created = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
    bubbles = ["one two three four five six seven eight nine ten", "short", "also short"]
    reading_delay_ms, typing_wpm, max_typing_ms = 250.0, 40.0, 900.0
    times = deliver_times(bubbles, created, reading_delay_ms, typing_wpm, max_typing_ms)

    first_typing = typing_ms(word_count(bubbles[0]), typing_wpm, max_typing_ms)
    assert first_typing == max_typing_ms  # 10 words at 40 wpm is 15 s, capped
    assert times[0] == created + timedelta(milliseconds=reading_delay_ms + first_typing)

    for index in range(1, len(bubbles)):
        typing = typing_ms(word_count(bubbles[index]), typing_wpm, max_typing_ms)
        gap = (times[index] - times[index - 1]).total_seconds() * 1000.0
        # max_typing_ms caps typing only; the 200 ms gap sits outside it.
        assert gap == pytest.approx(INTER_BUBBLE_GAP_MS + typing)
        assert gap > max_typing_ms if typing == max_typing_ms else True

    assert times == sorted(times) and len(set(times)) == len(times)


def test_delivery_times_are_empty_for_no_bubbles():
    assert deliver_times([], utcnow(), 0.0, 150.0, 8000.0) == []


# ---------------------------------------------------------------------------
# Phase 3 — naturalizer: split, merge-not-truncate (spec/05)
# ---------------------------------------------------------------------------


def test_a_multi_paragraph_draft_yields_between_two_and_five_bubbles():
    draft = "\n\n".join(f"paragraph {i}" for i in range(1, 4))
    bubbles = naturalize(draft)
    assert 2 <= len(bubbles) <= 5
    assert bubbles == ["paragraph 1", "paragraph 2", "paragraph 3"]


def test_six_paragraphs_merge_to_five_without_losing_content():
    seeds = [f"seed-{token}" for token in ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot")]
    draft = "\n\n".join(f"paragraph about {seed}" for seed in seeds)
    bubbles = naturalize(draft)
    assert len(bubbles) == 5
    joined = "\n".join(bubbles)
    for seed in seeds:
        assert seed in joined, f"{seed} was truncated instead of merged"
    # Merging joins with a newline and drops nothing else.
    assert joined.replace("\n", " ") == draft.replace("\n\n", " ").replace("\n", " ")


def test_a_long_draft_never_exceeds_five_bubbles():
    draft = "\n\n".join(f"paragraph {i}" for i in range(40))
    bubbles = naturalize(draft)
    assert len(bubbles) == 5
    for i in range(40):
        assert f"paragraph {i}" in "\n".join(bubbles)


def test_a_single_paragraph_is_one_bubble_and_empty_input_is_none():
    assert naturalize("just one line") == ["just one line"]
    assert naturalize("   \n  \n ") == []


def test_split_and_merge_are_independently_content_preserving():
    parts = split_paragraphs("a\n\nb\n\nc\n\nd\n\ne\n\nf\n\ng")
    assert parts == list("abcdefg")
    merged = merge_down(parts, 5)
    assert len(merged) == 5
    assert "".join(merged).replace("\n", "") == "abcdefg"


# ---------------------------------------------------------------------------
# Phase 2 — WSS grants: sign, validate, expire (spec/02 §WebSocket protocol)
# ---------------------------------------------------------------------------


def test_a_grant_is_two_base64url_segments_with_a_43_character_signature():
    token, _ = grants.issue("own_a", str(uuid.uuid4()), "turn-taking-thread/x")
    payload_segment, signature = token.split(".")
    assert len(token.split(".")) == 2
    assert len(signature) == 43  # HMAC-SHA256 base64url without padding
    assert re.fullmatch(r"[A-Za-z0-9_-]+", payload_segment)
    assert re.fullmatch(r"[A-Za-z0-9_-]+", signature)


def test_a_valid_grant_round_trips_its_owner_thread_and_channel():
    thread_id = str(uuid.uuid4())
    channel = f"turn-taking-thread/{thread_id}"
    token, expires_at = grants.issue("own_a", thread_id, channel)
    payload = grants.validate(token)
    assert payload is not None
    assert (payload["o"], payload["t"], payload["c"]) == ("own_a", thread_id, channel)
    assert expires_at > utcnow()


def test_the_grant_ttl_is_thirty_seconds():
    before = utcnow()
    _, expires_at = grants.issue("own_a", str(uuid.uuid4()), "turn-taking-thread/x")
    ttl = (expires_at - before).total_seconds()
    assert 25.0 <= ttl <= 35.0  # the suites' accepted window
    assert ttl == pytest.approx(settings.grant_ttl_seconds, abs=0.5)


def test_two_grants_for_one_channel_differ_by_nonce():
    channel = "turn-taking-thread/x"
    first, _ = grants.issue("own_a", "t", channel)
    second, _ = grants.issue("own_a", "t", channel)
    assert first != second
    assert grants.validate(first)["c"] == grants.validate(second)["c"]


@pytest.mark.parametrize("token", [
    "",
    "garbage",
    "one.two.three",
    "notbase64.notasignature",
])
def test_a_garbage_token_never_validates(token):
    assert grants.validate(token) is None


def test_a_tampered_signature_never_validates():
    token, _ = grants.issue("own_a", "t", "turn-taking-thread/x")
    payload_segment, signature = token.split(".")
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    assert grants.validate(f"{payload_segment}.{flipped}") is None


def test_a_tampered_payload_never_validates():
    token, _ = grants.issue("own_a", "t", "turn-taking-thread/x")
    other, _ = grants.issue("own_b", "t", "turn-taking-thread/x")
    assert grants.validate(f"{other.split('.')[0]}.{token.split('.')[1]}") is None


def test_an_expired_grant_stops_validating(monkeypatch):
    monkeypatch.setattr(settings, "grant_ttl_seconds", -1.0)
    token, expires_at = grants.issue("own_a", "t", "turn-taking-thread/x")
    assert expires_at < utcnow()
    assert grants.validate(token) is None


# ---------------------------------------------------------------------------
# Phase 3 — turn router decisions (spec/05 §Turn router)
# ---------------------------------------------------------------------------


def test_a_direct_mention_speaks():
    verdict = turn_router.decide(
        [{"content": "Grace, can you take a look at the export?"}],
        "You are Grace, a teammate in this chat.")
    assert verdict.decision == "speak"
    assert verdict.scores["directly_mentioned"] == 1.0


def test_traffic_addressed_to_someone_else_stays_silent():
    verdict = turn_router.decide(
        [{"content": "Bob, can you take a look at the export?"}],
        "You are Grace, a teammate in this chat.")
    assert verdict.decision == "stay_silent"


@pytest.mark.parametrize("content", ["ok", "okay!", "thanks", "got it", "lol"])
def test_a_bare_acknowledgement_stays_silent(content):
    verdict = turn_router.decide(
        [{"content": content}], "You are Grace, a teammate in this chat.")
    assert verdict.decision == "stay_silent"


def test_without_an_agent_name_the_router_speaks():
    # Nothing identifies the agent, so silence would be unattributable.
    assert turn_router.decide([{"content": "ok"}], None).decision == "speak"
    assert turn_router.decide([{"content": "anything at all"}], "").decision == "speak"


def test_the_router_can_produce_both_outcomes():
    prompt = "You are Grace, a teammate in this chat."
    outcomes = {
        turn_router.decide([{"content": "Grace, thoughts?"}], prompt).decision,
        turn_router.decide([{"content": "Bob, thoughts?"}], prompt).decision,
    }
    assert outcomes == {"speak", "stay_silent"}


def test_agent_names_are_read_from_the_system_prompt():
    assert "Grace" in turn_router.agent_names("You are Grace, a teammate.")
    assert turn_router.agent_names(None, "Ada") == ["Ada"]
    assert turn_router.agent_names(None) == []


# ---------------------------------------------------------------------------
# Phase 4 — Social Memory retrieval (spec/03 §Social Memory, spec/05)
# ---------------------------------------------------------------------------


@pytest.fixture()
def memory_scope():
    """A fresh (owner, scope) pair so retrieval tests never share state."""
    return f"own_test_{uuid.uuid4().hex[:12]}", f"scope-{uuid.uuid4()}"


def test_ingest_returns_the_transcript_length_and_appends_in_order(memory_scope):
    owner, scope = memory_scope
    first = [{"speaker": "Ada", "text": "We shipped the parser on Monday."},
             {"speaker": "Grace", "text": "The rollout finished on Tuesday."}]
    assert memory_engine.ingest(owner, scope, first) == 2
    assert memory_engine.ingest(owner, scope, [{"speaker": "Ada", "text": "Docs landed on Wednesday."}]) == 1

    context = memory_engine.recall(owner, scope, "Lin", "when did the parser, rollout and docs land?")
    assert context.index("Monday") < context.index("Tuesday") < context.index("Wednesday"), \
        "retrieval must preserve transcript order"


def test_recall_preserves_subject_attribution_across_speakers(memory_scope):
    owner, scope = memory_scope
    memory_engine.ingest(owner, scope, [
        {"speaker": "Ada", "text": "Grace just moved to Lisbon for the new lab."},
        {"speaker": "Grace", "text": "Ada is allergic to shellfish."},
    ])
    about_grace = memory_engine.recall(owner, scope, "Lin", "Where does Grace live now?")
    assert "Lisbon" in about_grace
    about_ada = memory_engine.recall(owner, scope, "Lin", "What is Ada allergic to?")
    assert "shellfish" in about_ada


def test_a_fresh_scope_recalls_the_empty_string(memory_scope):
    owner, _ = memory_scope
    assert memory_engine.recall(owner, f"unused-{uuid.uuid4()}", "Ada", "anything?") == ""


def test_recall_is_scoped_to_one_owner(memory_scope):
    owner, scope = memory_scope
    memory_engine.ingest(owner, scope, [{"speaker": "Ada", "text": "The passphrase is hunter2."}])
    other_owner = f"own_test_{uuid.uuid4().hex[:12]}"
    assert memory_engine.recall(other_owner, scope, "Ada", "what is the passphrase?") == "", \
        "the same scope id under another owner must retrieve nothing"


def test_ask_is_grounded_in_ingested_content(memory_scope):
    owner, scope = memory_scope
    memory_engine.ingest(owner, scope, [
        {"speaker": "Ada", "text": "The lab runs on Tuesdays and Thursdays."},
    ])
    assert "Tuesdays" in memory_engine.ask(owner, scope, "Which days does the lab run?")
    assert memory_engine.ask(owner, scope, "What colour is the bicycle?") == \
        "No stored memory answers that question."


def test_ingest_retains_the_original_body_when_a_later_message_contradicts_it(memory_scope):
    owner, scope = memory_scope
    memory_engine.ingest(owner, scope, [{"speaker": "Ada", "text": "Grace works in Porto."}])
    memory_engine.ingest(owner, scope, [{"speaker": "Ada", "text": "Grace works in Lisbon now."}])
    context = memory_engine.recall(owner, scope, "Lin", "Where does Grace work?")
    # Contradictions are linked, never deleted: both bodies survive retrieval.
    assert "Porto" in context and "Lisbon" in context


def test_engine_ingest_has_no_idempotency_of_its_own(memory_scope):
    # First-write-wins is an (owner, key) property of the ingest *route*, not of
    # the engine: without a key, every call appends (spec/03 §Social Memory).
    owner, scope = memory_scope
    body = [{"speaker": "Ada", "text": "Repeated exactly once per call."}]
    assert memory_engine.ingest(owner, scope, body) == 1
    assert memory_engine.ingest(owner, scope, body) == 1

    from sqlalchemy import func, select

    from humalike.db import session
    from humalike.storage import MemoryMessage

    with session() as s:
        stored = s.execute(
            select(func.count()).select_from(MemoryMessage)
            .where(MemoryMessage.owner_id == owner, MemoryMessage.scope_id == scope)
        ).scalar_one()
    assert stored == 2
