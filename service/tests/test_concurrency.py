"""Concurrency tests for idempotency and epoch atomicity.

spec/08 §Release gates requires a candidate to "preserve first-write
idempotency and stale-epoch atomicity under local concurrency tests". Both
properties are about what happens when two requests race, so both are driven
with `asyncio.gather` against the ASGI app rather than sequentially.

Phases covered: 4 (owner-wide `(owner,key)` idempotency) and 3 (respond
comparing and scheduling against the epoch atomically, with no charge for the
loser).
"""

from __future__ import annotations

import asyncio
import atexit
import os
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest

# Same scratch-database binding as the other delivery-discipline modules.
_SCRATCH_DB = Path(tempfile.gettempdir()) / f"humalike-delivery-tests-{os.getpid()}.db"
os.environ["HUMALIKE_DATABASE_URL"] = f"sqlite:///{_SCRATCH_DB}"
os.environ.setdefault("HUMALIKE_SECRET", "delivery-discipline-test-secret")


@atexit.register
def _remove_scratch_db() -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(_SCRATCH_DB) + suffix).unlink(missing_ok=True)


from sqlalchemy import func, select  # noqa: E402

from humalike.app import app  # noqa: E402
from humalike.auth import mint_key, resolve_bearer  # noqa: E402
from humalike.config import settings  # noqa: E402
from humalike.db import create_all, session  # noqa: E402
from humalike.scheduler import scheduler  # noqa: E402
from humalike.storage import CreditReservation, MemoryMessage, Schedule, UsageEvent  # noqa: E402

create_all()


def auth(key: str) -> dict[str, str]:
    return {"authorization": f"Bearer {key}"}


@pytest.fixture()
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
    for task in list(scheduler._tasks):
        task.cancel()


@pytest.fixture()
def key() -> str:
    return mint_key()


def owner_of(key: str) -> str:
    owner_id = resolve_bearer(f"Bearer {key}")
    assert owner_id is not None
    return owner_id


def stored_messages(owner_id: str, scope_id: str) -> list[str]:
    with session() as s:
        return [
            row.text for row in s.execute(
                select(MemoryMessage)
                .where(MemoryMessage.owner_id == owner_id, MemoryMessage.scope_id == scope_id)
                .order_by(MemoryMessage.seq)
            ).scalars().all()
        ]


def captured_credits(owner_id: str) -> int:
    with session() as s:
        return int(s.execute(
            select(func.coalesce(func.sum(UsageEvent.credits), 0))
            .where(UsageEvent.owner_id == owner_id)).scalar_one())


# ---------------------------------------------------------------------------
# Phase 4 — concurrent same-key ingest
# ---------------------------------------------------------------------------


async def test_concurrent_same_key_ingest_replays_one_result_with_one_side_effect(client, key):
    owner_id = owner_of(key)
    scope = f"concurrent-{uuid.uuid4()}"
    idempotency_key = f"key-{uuid.uuid4()}"

    # Same length so the response body cannot reveal which body won, different
    # text so the stored side effect can.
    bodies = [
        [{"speaker": "Ada", "text": f"attempt {index} first"},
         {"speaker": "Ada", "text": f"attempt {index} second"}]
        for index in range(6)
    ]
    responses = await asyncio.gather(*[
        client.post("/v1/social-memory/actions/ingest",
                    headers={**auth(key), "idempotency-key": idempotency_key},
                    json={"scope_id": scope, "transcript": body})
        for body in bodies
    ])

    assert all(response.status_code == 200 for response in responses)
    assert {response.text for response in responses} == {'{"ingested":2}'}, \
        "every racer must receive the first completed response"

    stored = stored_messages(owner_id, scope)
    assert stored in [[m["text"] for m in body] for body in bodies], \
        "exactly one body may reach memory"
    assert len(stored) == 2, f"expected one body's side effect, found {stored}"


async def test_concurrent_ingest_without_a_key_appends_every_body(client, key):
    # The control case: idempotency is opt-in, so without a key concurrent
    # calls are independent appends (spec/03 §Social Memory).
    owner_id = owner_of(key)
    scope = f"unkeyed-{uuid.uuid4()}"

    responses = await asyncio.gather(*[
        client.post("/v1/social-memory/actions/ingest", headers=auth(key),
                    json={"scope_id": scope, "transcript": [{"speaker": "Ada", "text": f"body {index}"}]})
        for index in range(4)
    ])

    assert all(response.json() == {"ingested": 1} for response in responses)
    assert sorted(stored_messages(owner_id, scope)) == [f"body {index}" for index in range(4)]


async def test_a_replay_racing_a_changed_body_still_returns_the_first_response(client, key):
    owner_id = owner_of(key)
    first_scope, other_scope = f"a-{uuid.uuid4()}", f"b-{uuid.uuid4()}"
    idempotency_key = f"key-{uuid.uuid4()}"

    first = await client.post(
        "/v1/social-memory/actions/ingest",
        headers={**auth(key), "idempotency-key": idempotency_key},
        json={"scope_id": first_scope, "transcript": [{"speaker": "Ada", "text": "the only body"}]})
    assert first.json() == {"ingested": 1}

    # Changed body and different scope, sent concurrently: the index is
    # (owner, key), so both replay and neither stores anything.
    replays = await asyncio.gather(*[
        client.post("/v1/social-memory/actions/ingest",
                    headers={**auth(key), "idempotency-key": idempotency_key},
                    json={"scope_id": scope, "transcript": [
                        {"speaker": "Bob", "text": "must not be stored"},
                        {"speaker": "Bob", "text": "must not be stored either"}]})
        for scope in (first_scope, other_scope)
    ])

    assert all(replay.json() == {"ingested": 1} for replay in replays)
    assert stored_messages(owner_id, first_scope) == ["the only body"]
    assert stored_messages(owner_id, other_scope) == []


# ---------------------------------------------------------------------------
# Phase 3 — concurrent respond against a stale epoch
# ---------------------------------------------------------------------------


async def test_a_stale_respond_racing_a_current_one_is_superseded_and_free(client, key):
    owner_id = owner_of(key)
    opened = await client.post("/v1/turn-taking/actions/open_thread", json={}, headers=auth(key))
    thread_id = opened.json()["thread"]["id"]

    epochs = []
    for _ in range(2):
        submitted = await client.post("/v1/turn-taking/actions/submit_messages", headers=auth(key), json={
            "thread_id": thread_id, "skip_decide": True,
            "messages": [{"sender": "Ada", "content": "another turn"}]})
        epochs.append(submitted.json()["turn_epoch"])
    stale_epoch, current_epoch = epochs
    assert current_epoch == stale_epoch + 1

    before = captured_credits(owner_id)
    stale, current = await asyncio.gather(
        client.post("/v1/turn-taking/actions/respond", headers=auth(key), json={
            "thread_id": thread_id, "content": "answering the old turn", "turn_epoch": stale_epoch}),
        client.post("/v1/turn-taking/actions/respond", headers=auth(key), json={
            "thread_id": thread_id, "content": "answering the current turn.\n\nIn two bubbles.",
            "turn_epoch": current_epoch}),
    )
    after = captured_credits(owner_id)

    assert stale.status_code == 200
    assert stale.json() == {"scheduled": [], "superseded": True}, "the exact superseded shape"
    assert list(stale.json()) == ["scheduled", "superseded"]

    assert current.status_code == 200
    assert current.json()["superseded"] is False
    assert 1 <= len(current.json()["scheduled"]) <= 5

    # Exactly one respond was billed: turn-taking plus Theory-of-Mind, once.
    assert after - before == settings.prices["turn-taking"] + settings.prices["theoryofmind"]
    with session() as s:
        assert s.execute(
            select(func.count()).select_from(CreditReservation)
            .where(CreditReservation.owner_id == owner_id,
                   CreditReservation.state == "reserved")).scalar_one() == 0

    # And only the current reply reached the schedule.
    with session() as s:
        rows = s.execute(select(Schedule).where(Schedule.thread_id == thread_id)).scalars().all()
    assert {row.reply_group for row in rows} == {rows[0].reply_group}
    assert all("current turn" in row.content or "two bubbles" in row.content.lower() for row in rows)


async def test_many_concurrent_stale_responds_all_return_the_same_free_shape(client, key):
    owner_id = owner_of(key)
    opened = await client.post("/v1/turn-taking/actions/open_thread", json={}, headers=auth(key))
    thread_id = opened.json()["thread"]["id"]
    submitted = await client.post("/v1/turn-taking/actions/submit_messages", headers=auth(key), json={
        "thread_id": thread_id, "skip_decide": True,
        "messages": [{"sender": "Ada", "content": "one turn only"}]})
    current_epoch = submitted.json()["turn_epoch"]

    before = captured_credits(owner_id)
    responses = await asyncio.gather(*[
        client.post("/v1/turn-taking/actions/respond", headers=auth(key), json={
            "thread_id": thread_id, "content": f"stale reply {index}",
            "turn_epoch": current_epoch - 1 - index})
        for index in range(5)
    ])

    assert {response.text for response in responses} == {'{"scheduled":[],"superseded":true}'}
    assert captured_credits(owner_id) == before
    with session() as s:
        assert s.execute(select(func.count()).select_from(Schedule)
                         .where(Schedule.thread_id == thread_id)).scalar_one() == 0


async def test_concurrent_submissions_advance_the_epoch_exactly_once_each(client, key):
    # submit_messages serializes by thread: every accepted batch advances the
    # epoch by exactly one, with no gaps and no repeats (spec/06 §Turn-taking).
    opened = await client.post("/v1/turn-taking/actions/open_thread", json={}, headers=auth(key))
    thread_id = opened.json()["thread"]["id"]

    responses = await asyncio.gather(*[
        client.post("/v1/turn-taking/actions/submit_messages", headers=auth(key), json={
            "thread_id": thread_id, "skip_decide": True,
            "messages": [{"sender": "Ada", "content": f"batch {index}"}]})
        for index in range(8)
    ])

    epochs = sorted(response.json()["turn_epoch"] for response in responses)
    assert epochs == list(range(1, 9)), f"epochs must be a gapless 1..N sequence, got {epochs}"
