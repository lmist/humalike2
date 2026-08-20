"""Exact Social Learning extract and foresee schemas and 422 shapes."""

from __future__ import annotations

import os
from pathlib import Path

os.environ["HUMALIKE_DATABASE_URL"] = "sqlite:///" + str(
    Path(__file__).resolve().parent / "test-learning-foresee.db"
)
os.environ["HUMALIKE_SECRET"] = "pytest-secret"
os.environ["HUMALIKE_SEED_KEYS"] = "ak_pytest_learning"

from fastapi.testclient import TestClient  # noqa: E402

from humalike.app import app  # noqa: E402
from humalike.auth import mint_key  # noqa: E402
from humalike.db import create_all  # noqa: E402
from humalike.engine.foresee import foresee, subject_names  # noqa: E402
from humalike.engine.learning import derive_channels, extract  # noqa: E402

# Mint at runtime so the module works regardless of which test file first
# imported humalike.config (env vars set above only apply on first import).
create_all()
AUTH = {"Authorization": f"Bearer {mint_key()}"}

TINY = {
    "transcript": {
        "source": "live-contract-tiny",
        "messages": [{"id": "t1", "speaker": "Ada", "text": "hello"}],
    }
}
RICH_MESSAGES = [
    {"id": "r1", "speaker": "Mira", "text": "yo, tea run at 3?", "channel": "lounge"},
    {"id": "r2", "speaker": "Sol", "text": "yep yep jasmine for me pls", "reply_to": "r1"},
    {"id": "r3", "speaker": "Mira", "text": "gotchu 🌿 no giant status update this time lol", "reply_to": "r2"},
    {"id": "r4", "speaker": "Sol", "text": "bless. tiny updates > essays", "reply_to": "r3"},
    {"id": "r5", "speaker": "Mira", "text": "shipping the patch after tea", "channel": "lounge"},
    {"id": "r6", "speaker": "Sol", "text": "nice, ping me when green", "reply_to": "r5"},
]
RICH = {"transcript": {"source": "live-contract-rich", "messages": RICH_MESSAGES}}
FORESEE_BODY = {
    "transcript": [
        {"speaker": "customer", "text": "The export failed twice."},
        {"speaker": "agent", "text": "Try clearing your cache."},
        {"speaker": "customer", "text": "I already did. I will just do it manually."},
    ],
    "candidate_reply": "Okay, reach out if you need anything else.",
    "agent_name": "agent",
    "subject_name": "customer",
    "system_prompt": "You are a concise support agent. Preserve the customer's trust and own unresolved issues.",
}

PROFILE_KEYS = [
    "summary", "register", "style", "lexicon", "banned_phrases", "address",
    "taboos", "humor", "roles", "norms", "in_jokes", "meta",
]


def _client() -> TestClient:
    return TestClient(app)


def _details(response):
    return response.json()["error"]["details"]


def _detail_at(details, loc):
    key = ".".join(str(part) for part in loc)
    for item in details:
        if ".".join(str(part) for part in item["loc"]) == key:
            return item
    return None


def _assert_422(response, expected):
    assert response.status_code == 422
    body = response.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "details"}
    assert body["error"]["code"] == "validation_failed"
    assert body["error"]["message"] == "request validation failed"
    details = body["error"]["details"]
    assert len(details) == len(expected)
    for loc, typ, msg in expected:
        item = _detail_at(details, loc)
        assert item is not None, details
        assert item["type"] == typ
        if msg is not None:
            assert item["msg"] == msg


def test_extract_missing_transcript():
    with _client() as client:
        response = client.post(
            "/v1/social-learning/actions/extract", json={}, headers=AUTH)
    _assert_422(response, [(["transcript"], "missing", "Field required")])


def test_extract_empty_transcript():
    with _client() as client:
        response = client.post(
            "/v1/social-learning/actions/extract",
            json={"transcript": {"messages": []}},
            headers=AUTH,
        )
    _assert_422(response, [(
        ["transcript", "messages"],
        "too_short",
        "List should have at least 1 item after validation, not 0",
    )])


def test_extract_unknown_field_ignored():
    with _client() as client:
        response = client.post(
            "/v1/social-learning/actions/extract",
            json={"transcript": {"messages": []}, "bogus": 1},
            headers=AUTH,
        )
    _assert_422(response, [(["transcript", "messages"], "too_short", None)])


def test_extract_message_missing_id():
    with _client() as client:
        response = client.post(
            "/v1/social-learning/actions/extract",
            json={"transcript": {"messages": [{"speaker": "a", "text": "b"}]}},
            headers=AUTH,
        )
    _assert_422(response, [(
        ["transcript", "messages", 0, "id"],
        "missing",
        "Field required",
    )])


def _assert_profile(profile, *, message_count, source):
    assert list(profile.keys()) == PROFILE_KEYS or set(profile.keys()) == set(PROFILE_KEYS)
    assert set(profile.keys()) == set(PROFILE_KEYS)
    assert isinstance(profile["summary"], str)
    register = profile["register"]
    assert set(register.keys()) == {"formality", "warmth", "casing", "notes", "confidence"}
    for key in ("formality", "warmth", "casing", "notes"):
        assert isinstance(register[key], str)
    assert isinstance(register["confidence"], float)
    assert 0.0 <= register["confidence"] <= 1.0
    style = profile["style"]
    assert set(style.keys()) == {"length", "formatting", "emoji"}
    for key in ("length", "formatting", "emoji"):
        assert isinstance(style[key], str)
    for key in ("lexicon", "banned_phrases", "taboos", "roles", "norms", "in_jokes"):
        assert isinstance(profile[key], list)
    address = profile["address"]
    assert set(address.keys()) == {"default", "deference"}
    assert isinstance(address["default"], str)
    assert isinstance(address["deference"], list)
    humor = profile["humor"]
    assert set(humor.keys()) == {"style", "rules"}
    assert isinstance(humor["style"], str)
    assert isinstance(humor["rules"], list) and all(isinstance(x, str) for x in humor["rules"])
    for item in profile["lexicon"]:
        assert set(item.keys()) == {"term", "meaning", "usage"}
        assert all(isinstance(item[k], str) for k in ("term", "meaning", "usage"))
    for item in profile["taboos"]:
        assert set(item.keys()) == {"rule", "scope", "evidence"}
        assert item["scope"] == "all"
        assert isinstance(item["evidence"], list) and all(isinstance(x, str) for x in item["evidence"])
    for item in profile["norms"]:
        assert set(item.keys()) == {"rule", "type", "evidence", "confidence"}
        assert item["type"] == "inferred_from_behavior"
        assert 0.0 <= item["confidence"] <= 1.0
        for ev in item["evidence"]:
            assert set(ev.keys()) == {"breach", "sanction"}
    meta = profile["meta"]
    assert set(meta.keys()) == {"source", "channels", "message_count"}
    assert meta["source"] == source
    assert meta["message_count"] == message_count
    assert isinstance(meta["channels"], list) and all(isinstance(x, str) for x in meta["channels"])


def test_extract_tiny_and_rich():
    with _client() as client:
        tiny = client.post(
            "/v1/social-learning/actions/extract", json=TINY, headers=AUTH)
        rich = client.post(
            "/v1/social-learning/actions/extract", json=RICH, headers=AUTH)
    assert tiny.status_code == 200
    assert rich.status_code == 200
    assert set(tiny.json().keys()) == {"profile", "prompt_block"}
    assert set(rich.json().keys()) == {"profile", "prompt_block"}
    assert tiny.json()["prompt_block"]
    assert rich.json()["prompt_block"]
    assert tiny.json()["prompt_block"] != rich.json()["prompt_block"]
    _assert_profile(tiny.json()["profile"], message_count=1, source="live-contract-tiny")
    _assert_profile(rich.json()["profile"], message_count=6, source="live-contract-rich")
    assert set(rich.json()["profile"]["meta"]["channels"]) == {"lounge", "unlabelled"}


def test_foresee_wrong_fields():
    with _client() as client:
        response = client.post(
            "/v1/foresee/actions/foresee",
            json={"conversation": [{"speaker": "customer", "text": "hello"}], "draft": "hi"},
            headers=AUTH,
        )
    _assert_422(response, [
        (["transcript"], "missing", "Field required"),
        (["candidate_reply"], "missing", "Field required"),
    ])


def test_foresee_empty_transcript():
    with _client() as client:
        response = client.post(
            "/v1/foresee/actions/foresee",
            json={"transcript": [], "candidate_reply": "I can help.", "bogus": 1},
            headers=AUTH,
        )
    _assert_422(response, [(
        ["transcript"],
        "too_short",
        "List should have at least 1 item after validation, not 0",
    )])


def test_foresee_valid():
    with _client() as client:
        response = client.post(
            "/v1/foresee/actions/foresee", json=FORESEE_BODY, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "mental_state", "predicted_reaction", "refined_reply", "refinement_rationale",
    }
    assert len(body["mental_state"]) == 1
    state = body["mental_state"][0]
    assert set(state.keys()) == {"name", "beliefs", "goals", "emotions"}
    assert state["name"] == "customer"
    assert all(isinstance(x, str) for x in state["beliefs"])
    assert all(isinstance(x, str) for x in state["goals"])
    assert any("export failed twice" in b.lower() for b in state["beliefs"])
    for emotion in state["emotions"]:
        assert set(emotion.keys()) == {"type", "intensity"}
        assert emotion["type"]
        assert 0.0 <= emotion["intensity"] <= 1.0
    assert len(body["predicted_reaction"]) == 1
    reaction = body["predicted_reaction"][0]
    assert set(reaction.keys()) == {"name", "summary", "predicted_message", "risk"}
    assert reaction["name"] == "customer"
    assert reaction["summary"] and reaction["predicted_message"]
    assert reaction["risk"] in ("low", "medium", "high")
    assert body["refined_reply"]
    assert "I already did" in body["refined_reply"]
    assert body["refinement_rationale"]


def test_derive_channels_rules():
    assert derive_channels([{"text": "hello"}]) == []
    assert derive_channels([
        {"channel": "lounge", "text": "a"},
        {"text": "b"},
        {"channel": "lounge", "text": "c"},
        {"channel": "ops", "text": "d"},
    ]) == ["lounge", "ops", "unlabelled"]
    assert derive_channels([
        {"channel": "lounge"}, {"channel": None}, {"channel": ""},
    ]) == ["lounge", "unlabelled"]


def test_extract_engine_source_and_counts():
    tiny = extract(
        [{"id": "t1", "speaker": "Ada", "text": "hello"}],
        "live-contract-tiny",
    )
    rich = extract(RICH_MESSAGES, "live-contract-rich")
    assert tiny["profile"]["meta"]["source"] == "live-contract-tiny"
    assert tiny["profile"]["meta"]["message_count"] == 1
    assert tiny["profile"]["meta"]["channels"] == []
    assert rich["profile"]["meta"]["channels"] == ["lounge", "unlabelled"]
    assert tiny["prompt_block"] != rich["prompt_block"]
    assert "Ada" in tiny["prompt_block"]
    assert "Mira" in rich["prompt_block"]


def test_foresee_engine_without_subject_name():
    transcript = [
        {"speaker": "Ada", "text": "The build failed."},
        {"speaker": "bot", "text": "Retry it."},
        {"speaker": "Sol", "text": "I will wait."},
    ]
    names = subject_names(transcript, "bot", None)
    assert names == ["Ada", "Sol"]
    result = foresee(transcript, "Okay.", agent_name="bot")
    assert [s["name"] for s in result["mental_state"]] == ["Ada", "Sol"]
    assert [s["name"] for s in result["predicted_reaction"]] == ["Ada", "Sol"]
    assert any("build failed" in b for b in result["mental_state"][0]["beliefs"])
