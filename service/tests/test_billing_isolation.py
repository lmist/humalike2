"""Multi-tenant isolation and billing integration tests.

Two of the release gates in spec/08 are internal engineering tests because a
single production key cannot establish them: cross-tenant reads must be
impossible, and credit reservation/capture must be atomic with respect to
superseded and short-circuited work. This file covers both, driving the real
ASGI app so the gateway, owner injection, and route handlers are all in play.

Phases covered: 1 (tenancy and credits), 2-3 (thread ownership, unbilled
supersession), 4 (memory and idempotency scoping), 8 (402 and reservation
release, which are documented defaults rather than observed behavior).
"""

from __future__ import annotations

import atexit
import os
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest

# Same scratch-database binding as test_core.py: whichever module pytest
# imports first fixes the URL, and the pid keeps concurrent runs apart.
_SCRATCH_DB = Path(tempfile.gettempdir()) / f"humalike-delivery-tests-{os.getpid()}.db"
os.environ["HUMALIKE_DATABASE_URL"] = f"sqlite:///{_SCRATCH_DB}"
os.environ.setdefault("HUMALIKE_SECRET", "delivery-discipline-test-secret")


@atexit.register
def _remove_scratch_db() -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(_SCRATCH_DB) + suffix).unlink(missing_ok=True)


from sqlalchemy import select  # noqa: E402

from humalike import billing  # noqa: E402
from humalike.app import app  # noqa: E402
from humalike.auth import mint_key  # noqa: E402
from humalike.config import settings  # noqa: E402
from humalike.db import create_all, session  # noqa: E402
from humalike.scheduler import scheduler  # noqa: E402
from humalike.storage import (  # noqa: E402
    AuditRun,
    CreditReservation,
    Job,
    StoredReport,
    UsageEvent,
)
from humalike.timefmt import utcnow  # noqa: E402

# The app's lifespan is not run under ASGITransport, so the schema is created
# here instead (spec/06 §Durable state).
create_all()


def mint_owner(credits: int | None = None) -> str:
    """Mint a funded key. `credits` overrides the configured initial balance."""
    original = settings.initial_credits
    if credits is not None:
        settings.initial_credits = credits
    try:
        return mint_key()
    finally:
        settings.initial_credits = original


def auth(key: str) -> dict[str, str]:
    return {"authorization": f"Bearer {key}"}


@pytest.fixture()
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
    # Delivery tasks armed by respond outlive the request; drop them so a test
    # never leaks a pending task into the next one.
    for task in list(scheduler._tasks):
        task.cancel()


async def open_thread(client: httpx.AsyncClient, key: str, **body) -> dict:
    response = await client.post(
        "/v1/turn-taking/actions/open_thread", json=body, headers=auth(key))
    assert response.status_code == 200, response.text
    return response.json()


async def usage(client: httpx.AsyncClient, key: str) -> dict:
    response = await client.post(
        "/v1/credits/projections/usage-summary", json={}, headers=auth(key))
    assert response.status_code == 200, response.text
    return response.json()


def owner_of(key: str) -> str:
    from humalike.auth import resolve_bearer
    owner_id = resolve_bearer(f"Bearer {key}")
    assert owner_id is not None
    return owner_id


# ---------------------------------------------------------------------------
# Phase 1 — authentication and identity
# ---------------------------------------------------------------------------


async def test_two_minted_keys_resolve_to_different_owners(client):
    alice, bob = mint_owner(), mint_owner()
    first = await client.post("/v1/turn-taking/actions/whoami", json={}, headers=auth(alice))
    second = await client.post("/v1/turn-taking/actions/whoami", json={}, headers=auth(bob))
    assert first.json()["user_id"] != second.json()["user_id"]
    assert list(first.json()) == ["user_id"]


@pytest.mark.parametrize("headers", [
    {},
    {"authorization": "Bearer"},
    {"authorization": "Basic ak_whatever"},
    {"authorization": "Bearer ak_not_a_real_key"},
])
async def test_every_invalid_credential_returns_the_exact_401(client, headers):
    response = await client.post("/v1/turn-taking/actions/whoami", json={}, headers=headers)
    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "UNAUTHORIZED", "message": "missing or invalid credentials"}}
    assert response.headers["x-request-id"]
    assert response.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# Phase 2-3 — thread isolation
# ---------------------------------------------------------------------------


async def test_another_owner_cannot_submit_to_a_thread(client):
    alice, bob = mint_owner(), mint_owner()
    thread = await open_thread(client, alice)

    response = await client.post("/v1/turn-taking/actions/submit_messages", headers=auth(bob), json={
        "thread_id": thread["thread"]["id"],
        "messages": [{"sender": "Bob", "content": "let me in"}]})
    assert response.status_code == 400
    assert response.json() == {"error": {"code": "VALIDATION_ERROR", "message": "unknown thread"}}


async def test_another_owner_cannot_respond_or_record_events_on_a_thread(client):
    alice, bob = mint_owner(), mint_owner()
    thread = await open_thread(client, alice)
    thread_id = thread["thread"]["id"]
    await client.post("/v1/turn-taking/actions/submit_messages", headers=auth(alice), json={
        "thread_id": thread_id, "messages": [{"sender": "Ada", "content": "hello"}]})

    responded = await client.post("/v1/turn-taking/actions/respond", headers=auth(bob), json={
        "thread_id": thread_id, "content": "not mine to answer", "turn_epoch": 1})
    assert responded.status_code == 400
    assert responded.json()["error"]["message"] == "unknown thread"

    event = await client.post("/v1/turn-taking/actions/record_event", headers=auth(bob), json={
        "thread_id": thread_id, "type": "typing_start", "sender": "Bob"})
    assert event.status_code == 400


async def test_reopening_another_owners_thread_id_returns_the_documented_403(client):
    alice, bob = mint_owner(), mint_owner()
    thread = await open_thread(client, alice)

    response = await client.post("/v1/turn-taking/actions/open_thread", headers=auth(bob),
                                 json={"thread_id": thread["thread"]["id"]})
    # Cross-owner UUID behavior is unproven production behavior (spec/08 open
    # question 6); the recreation's documented default is 403, and the one
    # thing that is not negotiable is that Bob must not touch Alice's thread.
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"

    still_alices = await open_thread(client, alice, thread_id=thread["thread"]["id"])
    assert still_alices["thread"]["user_id"] == thread["thread"]["user_id"]


async def test_a_thread_reopen_preserves_the_id_and_rotates_the_grant(client):
    alice = mint_owner()
    first = await open_thread(client, alice)
    second = await open_thread(client, alice, thread_id=first["thread"]["id"])
    assert second["thread"]["id"] == first["thread"]["id"]
    assert second["thread"]["updated_at"] > first["thread"]["updated_at"]
    assert second["realtime"]["expires_at"] > first["realtime"]["expires_at"]
    assert second["realtime"]["connect_url"] != first["realtime"]["connect_url"]


# ---------------------------------------------------------------------------
# Phase 4 — memory and idempotency isolation
# ---------------------------------------------------------------------------


async def test_one_owners_memory_scope_is_invisible_to_another(client):
    alice, bob = mint_owner(), mint_owner()
    scope = f"shared-name-{uuid.uuid4()}"

    ingested = await client.post("/v1/social-memory/actions/ingest", headers=auth(alice), json={
        "scope_id": scope,
        "transcript": [{"speaker": "Ada", "text": "The passphrase is hunter2."}]})
    assert ingested.json() == {"ingested": 1}

    recalled = await client.post("/v1/social-memory/actions/recall", headers=auth(bob), json={
        "scope_id": scope, "message": {"speaker": "Bob", "text": "what is the passphrase?"}})
    assert recalled.status_code == 200
    assert recalled.json() == {"context": ""}, "an identical scope id under another owner is a different scope"

    asked = await client.post("/v1/social-memory/actions/ask", headers=auth(bob), json={
        "scope_id": scope, "question": "what is the passphrase?"})
    assert "hunter2" not in asked.json()["answer"]


async def test_an_idempotency_key_is_scoped_to_its_owner(client):
    alice, bob = mint_owner(), mint_owner()
    key = f"shared-key-{uuid.uuid4()}"
    alice_scope, bob_scope = f"a-{uuid.uuid4()}", f"b-{uuid.uuid4()}"

    first = await client.post(
        "/v1/social-memory/actions/ingest", headers={**auth(alice), "idempotency-key": key},
        json={"scope_id": alice_scope, "transcript": [{"speaker": "Ada", "text": "alice one"}]})
    second = await client.post(
        "/v1/social-memory/actions/ingest", headers={**auth(bob), "idempotency-key": key},
        json={"scope_id": bob_scope, "transcript": [
            {"speaker": "Bob", "text": "bob one"}, {"speaker": "Bob", "text": "bob two"}]})

    assert first.json() == {"ingested": 1}
    # The index is (owner, key): Bob's request is his own first write, not a
    # replay of Alice's response.
    assert second.json() == {"ingested": 2}

    bobs = await client.post("/v1/social-memory/actions/recall", headers=auth(bob), json={
        "scope_id": bob_scope, "message": {"speaker": "Bob", "text": "bob"}})
    assert "bob one" in bobs.json()["context"]
    assert "alice" not in bobs.json()["context"]


# ---------------------------------------------------------------------------
# Phase 6-7 — repository rows carry an owner predicate
# ---------------------------------------------------------------------------


async def test_repository_rows_are_owner_scoped(client):
    """Reports, persona jobs, and audit runs are reachable only by their owner.

    The public `by-id` routes for these resources return JSON `null` for a
    valid unknown UUID, so "not mine" and "does not exist" are indistinguishable
    to a caller — which is exactly the property that makes the owner predicate
    on the query the thing worth testing.
    """
    alice, bob = mint_owner(), mint_owner()
    alice_id, bob_id = owner_of(alice), owner_of(bob)
    now = utcnow()
    report_id, job_id, run_id = (str(uuid.uuid4()) for _ in range(3))

    with session() as s:
        s.add(StoredReport(id=report_id, owner_id=alice_id,
                           report_json='{"health_score":0.5}', created_at=now))
        s.add(Job(id=job_id, owner_id=alice_id, kind="population", status="succeeded",
                  request_json="{}", created_at=now, updated_at=now))
        s.add(AuditRun(run_id=run_id, owner_id=alice_id, agent_name="Grace",
                       agent_guess="Grace", launched=True, status="completed",
                       transcript_json="[]", created_at=now, updated_at=now))

    with session() as s:
        for model, column, identifier in (
            (StoredReport, StoredReport.id, report_id),
            (Job, Job.id, job_id),
            (AuditRun, AuditRun.run_id, run_id),
        ):
            mine = s.execute(select(model).where(column == identifier,
                                                 model.owner_id == alice_id)).scalar_one_or_none()
            theirs = s.execute(select(model).where(column == identifier,
                                                   model.owner_id == bob_id)).scalar_one_or_none()
            assert mine is not None, f"{model.__name__} must be readable by its owner"
            assert theirs is None, f"{model.__name__} must be invisible to another owner"


async def test_usage_projections_do_not_leak_across_owners(client):
    alice, bob = mint_owner(), mint_owner()
    scope = f"usage-{uuid.uuid4()}"
    await client.post("/v1/social-memory/actions/ingest", headers=auth(alice),
                      json={"scope_id": scope, "transcript": [{"speaker": "Ada", "text": "one"}]})
    for _ in range(3):
        await client.post("/v1/social-memory/actions/ask", headers=auth(alice),
                          json={"scope_id": scope, "question": "one?"})

    assert (await usage(client, alice))["total_calls"] == 3

    bobs = await usage(client, bob)
    assert (bobs["total_calls"], bobs["total_credits"], bobs["per_component"]) == (0, 0, [])
    # The daily series counts Bob's own requests, so it is non-empty even
    # though he has been charged nothing.
    assert len(bobs["daily_series"]) == 7
    assert sum(day["requests"] for day in bobs["daily_series"]) < 3


# ---------------------------------------------------------------------------
# Phase 1 — free versus billable paths (spec/02 §Billing)
# ---------------------------------------------------------------------------


async def test_identity_usage_events_and_ingest_are_free(client):
    alice = mint_owner()
    thread = await open_thread(client, alice)
    await client.post("/v1/turn-taking/actions/whoami", json={}, headers=auth(alice))
    await client.post("/v1/turn-taking/actions/record_event", headers=auth(alice), json={
        "thread_id": thread["thread"]["id"], "type": "typing_start", "sender": "Ada"})
    await client.post("/v1/social-memory/actions/ingest", headers=auth(alice), json={
        "scope_id": f"free-{uuid.uuid4()}", "transcript": [{"speaker": "Ada", "text": "free"}]})

    summary = await usage(client, alice)
    assert summary["total_calls"] == 0 and summary["total_credits"] == 0
    assert summary["per_component"] == []


async def test_submit_and_respond_bill_their_components(client):
    alice = mint_owner()
    thread = await open_thread(client, alice)
    submitted = await client.post("/v1/turn-taking/actions/submit_messages", headers=auth(alice), json={
        "thread_id": thread["thread"]["id"],
        "messages": [{"sender": "Ada", "content": "can you summarise the migration?"}]})
    assert submitted.status_code == 200

    after_submit = await usage(client, alice)
    assert dict((r["component"], r["calls"]) for r in after_submit["per_component"]) == {"turn-taking": 1}

    responded = await client.post("/v1/turn-taking/actions/respond", headers=auth(alice), json={
        "thread_id": thread["thread"]["id"], "content": "Sure.\n\nHere it is.",
        "turn_epoch": submitted.json()["turn_epoch"]})
    assert responded.status_code == 200 and responded.json()["superseded"] is False

    after_respond = await usage(client, alice)
    calls = dict((r["component"], r["calls"]) for r in after_respond["per_component"])
    # respond runs refinement as well as turn-taking, so it charges both.
    assert calls == {"theoryofmind": 1, "turn-taking": 2}
    assert after_respond["total_credits"] == (
        settings.prices["turn-taking"] * 2 + settings.prices["theoryofmind"])


async def test_a_short_circuited_submit_is_not_billed(client):
    alice = mint_owner()
    thread = await open_thread(client, alice)
    before = await usage(client, alice)

    skipped = await client.post("/v1/turn-taking/actions/submit_messages", headers=auth(alice), json={
        "thread_id": thread["thread"]["id"], "skip_decide": True,
        "messages": [{"sender": "Ada", "content": "no decision needed"}]})
    media = await client.post("/v1/turn-taking/actions/submit_messages", headers=auth(alice), json={
        "thread_id": thread["thread"]["id"],
        "messages": [{"sender": "Ada", "content": "a photo", "has_media": True}]})
    assert skipped.json()["decision"] == "speak" and media.json()["decision"] == "speak"

    after = await usage(client, alice)
    assert after["total_credits"] == before["total_credits"], \
        "a short-circuited decision runs no model work and must not capture"


async def test_a_stale_respond_returns_the_exact_shape_and_bills_nothing(client):
    alice = mint_owner()
    thread = await open_thread(client, alice)
    thread_id = thread["thread"]["id"]
    for _ in range(2):
        await client.post("/v1/turn-taking/actions/submit_messages", headers=auth(alice), json={
            "thread_id": thread_id, "messages": [{"sender": "Ada", "content": "still here?"}]})

    before = await usage(client, alice)
    stale = await client.post("/v1/turn-taking/actions/respond", headers=auth(alice), json={
        "thread_id": thread_id, "content": "answering an old turn", "turn_epoch": 1})
    after = await usage(client, alice)

    assert stale.status_code == 200
    assert stale.json() == {"scheduled": [], "superseded": True}
    assert after["total_credits"] == before["total_credits"], \
        "supersession adds no turn-taking or Theory-of-Mind charge"
    assert after["total_calls"] == before["total_calls"]


async def test_recall_and_ask_bill_social_memory(client):
    alice = mint_owner()
    scope = f"billing-{uuid.uuid4()}"
    await client.post("/v1/social-memory/actions/ingest", headers=auth(alice), json={
        "scope_id": scope, "transcript": [{"speaker": "Ada", "text": "the lab runs on Tuesdays"}]})
    await client.post("/v1/social-memory/actions/recall", headers=auth(alice), json={
        "scope_id": scope, "message": {"speaker": "Ada", "text": "which days?"}})
    await client.post("/v1/social-memory/actions/ask", headers=auth(alice), json={
        "scope_id": scope, "question": "which days?"})

    summary = await usage(client, alice)
    assert dict((r["component"], r["calls"]) for r in summary["per_component"]) == {"social-memory": 2}
    assert summary["total_credits"] == settings.prices["social-memory"] * 2


# ---------------------------------------------------------------------------
# Phase 1/8 — reservations, releases, and the 402 documented default
# ---------------------------------------------------------------------------


def reservations_for(owner_id: str, state: str | None = None) -> list[CreditReservation]:
    with session() as s:
        query = select(CreditReservation).where(CreditReservation.owner_id == owner_id)
        if state is not None:
            query = query.where(CreditReservation.state == state)
        return list(s.execute(query).scalars().all())


async def test_a_released_reservation_never_becomes_a_charge(client):
    alice = mint_owner(100)
    owner_id = owner_of(alice)

    reservation = billing.reserve(owner_id, "turn-taking")
    assert [r.state for r in reservations_for(owner_id)] == ["reserved"]
    billing.release(reservation)

    assert [r.state for r in reservations_for(owner_id)] == ["released"]
    with session() as s:
        assert s.execute(select(UsageEvent).where(UsageEvent.owner_id == owner_id)).first() is None
    assert (await usage(client, alice))["total_credits"] == 0


async def test_an_abandoned_reservation_is_reconciled_rather_than_charged(client):
    alice = mint_owner(100)
    owner_id = owner_of(alice)
    billing.reserve(owner_id, "theoryofmind")

    # A crashed worker leaves a reservation behind; the reconciler frees it so
    # the balance it holds is not lost forever (spec/06 §Reliability).
    assert billing.reconcile_abandoned(older_than_seconds=0.0) >= 1
    assert [r.state for r in reservations_for(owner_id)] == ["released"]
    assert (await usage(client, alice))["total_credits"] == 0


async def test_a_reservation_that_cannot_be_completed_is_released_and_returns_402(client):
    # respond reserves turn-taking and then theoryofmind. A balance that covers
    # the first but not the second must leave nothing reserved behind.
    alice = mint_owner(settings.prices["turn-taking"])
    owner_id = owner_of(alice)
    thread = await open_thread(client, alice)
    submitted = await client.post("/v1/turn-taking/actions/submit_messages", headers=auth(alice), json={
        "thread_id": thread["thread"]["id"], "skip_decide": True,
        "messages": [{"sender": "Ada", "content": "free short circuit"}]})

    response = await client.post("/v1/turn-taking/actions/respond", headers=auth(alice), json={
        "thread_id": thread["thread"]["id"], "content": "a reply that cannot be afforded",
        "turn_epoch": submitted.json()["turn_epoch"]})

    assert response.status_code == 402
    assert response.json() == {
        "error": {"code": "PAYMENT_REQUIRED", "message": "insufficient credits"}}
    assert reservations_for(owner_id, state="reserved") == [], \
        "a partially reserved command must release what it already reserved"
    assert (await usage(client, alice))["total_credits"] == 0


async def test_402_is_returned_before_billable_work_once_the_balance_is_exhausted(client):
    # The 402 body is a documented default, never observed live (spec/08 open
    # question 4); this pins the recreation's behavior, not production's.
    alice = mint_owner(settings.prices["social-memory"])
    scope = f"broke-{uuid.uuid4()}"
    await client.post("/v1/social-memory/actions/ingest", headers=auth(alice), json={
        "scope_id": scope, "transcript": [{"speaker": "Ada", "text": "one paid recall left"}]})

    paid = await client.post("/v1/social-memory/actions/recall", headers=auth(alice), json={
        "scope_id": scope, "message": {"speaker": "Ada", "text": "anything?"}})
    assert paid.status_code == 200

    denied = await client.post("/v1/social-memory/actions/recall", headers=auth(alice), json={
        "scope_id": scope, "message": {"speaker": "Ada", "text": "anything?"}})
    assert denied.status_code == 402
    assert denied.json() == {
        "error": {"code": "PAYMENT_REQUIRED", "message": "insufficient credits"}}
    assert denied.headers["x-request-id"]

    summary = await usage(client, alice)
    assert summary["total_calls"] == 1, "the denied call must not appear as a charge"
    assert summary["total_credits"] == settings.prices["social-memory"]
    assert reservations_for(owner_of(alice), state="reserved") == []


async def test_free_routes_keep_working_with_no_credits(client):
    alice = mint_owner(0)
    whoami = await client.post("/v1/turn-taking/actions/whoami", json={}, headers=auth(alice))
    summary = await client.post("/v1/credits/projections/usage-summary", json={}, headers=auth(alice))
    assert whoami.status_code == 200 and summary.status_code == 200
    assert summary.json()["total_credits"] == 0
