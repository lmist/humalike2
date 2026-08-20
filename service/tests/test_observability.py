"""Focused coverage for deterministic Social Observability and full audits."""

from __future__ import annotations

import os
import time
from uuid import uuid4

os.environ["HUMALIKE_DATABASE_URL"] = (
    f"sqlite:////tmp/humalike-observability-{uuid4()}.db"
)
os.environ["HUMALIKE_SECRET"] = "observability-test-secret"

import pytest
from fastapi.testclient import TestClient

from humalike import billing
from humalike.app import app
from humalike.auth import mint_key, resolve_bearer
from humalike.engine.audit import estimated_tokens, guess_agent, parse_raw_text


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as client:
        key = mint_key()
        yield client, {"Authorization": f"Bearer {key}"}, resolve_bearer(
            f"Bearer {key}"
        )


def test_parser_accepts_supported_lines_and_preserves_first_colon():
    messages = parse_raw_text(
        "[10:01] Support Bot: status: still broken\n"
        "Casey Jones: retry failed\n"
        "not a conversation line"
    )
    assert [(item["speaker"], item["text"]) for item in messages] == [
        ("Support Bot", "status: still broken"),
        ("Casey Jones", "retry failed"),
    ]
    assert [item["id"] for item in messages] == ["m1", "m2"]
    assert all(item["timestamp"] is None for item in messages)
    assert parse_raw_text("This text contains no labelled conversation.") == []
    assert guess_agent(["Casey", "support_bot", "Jordan"]) == "support_bot"
    assert guess_agent(["Casey", "Jordan"]) == "Jordan"
    assert guess_agent(["Casey", "Jordan", "Morgan"]) is None


def test_token_estimate_and_prepare_validation_order(api):
    client, headers, _ = api
    assert estimated_tokens("x" * 300_000) == 120_300
    response = client.post(
        "/v1/social-observability/actions/audit_prepare",
        headers=headers,
        json={"raw_text": "x" * 300_000},
    )
    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": (
                "This paste is too large to read: about 120,300 tokens, "
                "and the audit accepts about 32,768. Send at most 250 messages."
            ),
            "details": [{
                "field": "raw_text",
                "message": "at most ~32768 tokens allowed",
            }],
        }
    }

    too_many = "\n".join(f"Casey: message {index}" for index in range(251))
    response = client.post(
        "/v1/social-observability/actions/audit_prepare",
        headers=headers,
        json={"raw_text": too_many},
    )
    assert response.status_code == 400
    assert response.json()["error"]["message"].startswith(
        "This transcript has 251 messages;"
    )


def test_launch_is_first_write_wins_and_projection_is_monotonic(api):
    client, headers, owner_id = api
    raw_text = "\n".join([
        "[10:01] Casey: the export broke again",
        "[10:02] support_bot: Have you tried clearing your cache?",
        "[10:03] Casey: yes, twice already",
        "[10:04] support_bot: Please retry later.",
        "[10:05] Casey: that does not help",
        "[10:06] support_bot: Is there anything else?",
    ])
    prepared = client.post(
        "/v1/social-observability/actions/audit_prepare",
        headers=headers,
        json={"raw_text": raw_text},
    )
    assert prepared.status_code == 200
    run_id = prepared.json()["run_id"]

    before = client.post(
        "/v1/social-observability/projections/audit-run",
        headers=headers,
        json={"run_id": run_id},
    ).json()
    assert before["agent_name"] == "support_bot"
    assert before["report"] is before["read"] is before["verdicts"] is None
    assert before["replies"] == []

    launch = client.post(
        "/v1/social-observability/actions/audit_launch",
        headers=headers,
        json={"run_id": run_id, "agent_name": "support_bot"},
    )
    assert launch.json() == {
        "run_id": run_id,
        "agent_name": "support_bot",
        "status": "queued",
    }
    billed = billing.usage_summary(owner_id)
    repeat = client.post(
        "/v1/social-observability/actions/audit_launch",
        headers=headers,
        json={"run_id": run_id, "agent_name": "Casey"},
    )
    assert repeat.json()["agent_name"] == "support_bot"

    signatures = []
    final = None
    for _ in range(100):
        projection = client.post(
            "/v1/social-observability/projections/audit-run",
            headers=headers,
            json={"run_id": run_id},
        ).json()
        signature = (
            projection["report"] is not None,
            projection["read"] is not None,
            projection["verdicts"] is not None,
            len(projection["replies"]),
        )
        signatures.append(signature)
        if (
            all(signature[:3])
            and signature[3] == len(projection["verdicts"])
            and signature[3] > 0
        ):
            final = projection
            break
        time.sleep(0.04)

    assert final is not None
    for earlier, later in zip(signatures, signatures[1:]):
        assert all(not previous or current for previous, current in zip(
            earlier[:3], later[:3]
        ))
        assert later[3] >= earlier[3]
    first_seen = [
        next(index for index, item in enumerate(signatures) if item[position])
        for position in range(3)
    ]
    assert first_seen == sorted(first_seen)
    assert all(user["user_id"] is None for user in final["report"]["per_user"])
    assert [item["index"] for item in final["verdicts"]] == [1, 3, 5]
    assert [item["index"] for item in final["replies"]] == [1, 3, 5]

    relaunch = client.post(
        "/v1/social-observability/actions/audit_launch",
        headers=headers,
        json={"run_id": run_id, "agent_name": "Casey"},
    )
    assert relaunch.json() == {
        "run_id": run_id,
        "agent_name": "support_bot",
        "status": "completed",
    }
    after = client.post(
        "/v1/social-observability/projections/audit-run",
        headers=headers,
        json={"run_id": run_id},
    ).json()
    assert after == final
    after_usage = billing.usage_summary(owner_id)
    before_component = next(
        item for item in billed["per_component"]
        if item["component"] == "social-observability"
    )
    after_component = next(
        item for item in after_usage["per_component"]
        if item["component"] == "social-observability"
    )
    assert after_component == before_component
    assert after_usage["total_credits"] == billed["total_credits"]
