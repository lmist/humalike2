"""Turn-taking routes (spec/03): open_thread, submit_messages, record_event,
respond. Epoch, grant, pacing, and supersession invariants live here.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

from fastapi import APIRouter, Request

from .. import billing, metrics
from ..config import settings
from ..db import session
from ..engine import memory as memory_engine
from ..engine import router as turn_router
from ..engine.naturalizer import naturalize
from ..engine.pacing import deliver_times, resolve_pacing
from ..engine.refinement import refine
from ..errors import payment_required, semantic_validation_error
from ..grants import issue
from ..ids import new_uuid
from ..scheduler import scheduler
from ..schemas.realtime import (
    OpenThreadRequest,
    RecordEventRequest,
    RespondRequest,
    SubmitRequest,
)
from ..storage import Outbox, RouterTrace, Schedule, Thread, ThreadMessage, dumps
from ..timefmt import ts, utcnow

router = APIRouter()

_thread_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _connect_url(request: Request, token: str) -> str:
    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}/v1/ws/turn-taking-thread?token={token}"


def _channel(thread_id: str) -> str:
    return f"turn-taking-thread/{thread_id}"


def _thread_payload(thread: Thread, request: Request) -> dict:
    token, expires_at = issue(thread.owner_id, thread.id, _channel(thread.id))
    return {
        "thread": {
            "id": thread.id,
            "user_id": thread.owner_id,
            "created_at": ts(thread.created_at),
            "updated_at": ts(thread.updated_at),
        },
        "channel": _channel(thread.id),
        "realtime": {
            "connect_url": _connect_url(request, token),
            "expires_at": ts(expires_at),
        },
    }


@router.post("/v1/turn-taking/actions/open_thread")
async def open_thread(request: Request, body: OpenThreadRequest):
    owner_id = request.state.owner_id
    now = utcnow()
    requested_id = str(body.thread_id) if body.thread_id else None
    with session() as s:
        thread = s.get(Thread, requested_id) if requested_id else None
        if thread is not None and thread.owner_id != owner_id:
            # Cross-owner UUID behavior is untested production behavior
            # (spec/08 open question 6); local safety: never disclose or touch
            # another owner's thread. Documented-default 403.
            from ..errors import forbidden
            return forbidden()
        if thread is None:
            thread = Thread(
                id=requested_id or new_uuid(),
                owner_id=owner_id,
                created_at=now,
                updated_at=now,
                turn_epoch=0,
            )
            s.add(thread)
        else:
            thread.updated_at = now
        if body.integrations is not None:
            if body.integrations.social_memory is not None:
                thread.memory_bank_id = body.integrations.social_memory.memory_bank_id
            if body.integrations.social_signals is not None:
                thread.signals_json = dumps(
                    body.integrations.social_signals.model_dump())
        payload = _thread_payload(thread, request)
    return payload


def _recalled_context(owner_id: str, thread: Thread, messages: list[dict]) -> str:
    if not thread.memory_bank_id or not messages:
        return ""
    last = messages[-1]
    return memory_engine.recall(
        owner_id, thread.memory_bank_id, last["sender"],
        " ".join(m["content"] for m in messages))


@router.post("/v1/turn-taking/actions/submit_messages")
async def submit_messages(request: Request, body: SubmitRequest):
    owner_id = request.state.owner_id
    thread_id = str(body.thread_id)
    async with _thread_locks[thread_id]:
        with session() as s:
            thread = s.get(Thread, thread_id)
            if thread is None or thread.owner_id != owner_id:
                return semantic_validation_error("unknown thread")
            messages = [m.model_dump() for m in body.messages]
            short_circuit = body.skip_decide or any(m["has_media"] for m in messages)

            reservation = None
            if not short_circuit:
                try:
                    reservation = billing.reserve(owner_id, "turn-taking")
                except billing.InsufficientCredits:
                    return payment_required()

            started = time.monotonic()
            now = utcnow()
            new_epoch = thread.turn_epoch + 1
            thread.turn_epoch = new_epoch
            thread.updated_at = now
            metrics.record_epoch_advance()
            for m in messages:
                s.add(ThreadMessage(
                    thread_id=thread_id, owner_id=owner_id, epoch=new_epoch,
                    sender=m["sender"], content=m["content"],
                    has_media=bool(m["has_media"]), client_ts=m["client_ts"],
                    created_at=now))

            if short_circuit:
                decision = "speak"
                scores = {"short_circuit": 1.0}
            else:
                verdict = turn_router.decide(messages, body.system_prompt)
                decision = verdict.decision
                scores = verdict.scores
            s.add(RouterTrace(
                thread_id=thread_id, owner_id=owner_id, epoch=new_epoch,
                decision=decision, scores_json=dumps(scores),
                latency_ms=(time.monotonic() - started) * 1000.0,
                created_at=now))

            if decision == "stay_silent":
                # The captured silence response is exact (spec/03).
                recalled = ""
            else:
                recalled = _recalled_context(owner_id, thread, messages)

        if reservation is not None:
            billing.capture(reservation)
    return {
        "decision": decision,
        "turn_epoch": new_epoch,
        "tags": [],
        "recalled_context": recalled,
    }


@router.post("/v1/turn-taking/actions/record_event")
async def record_event(request: Request, body: RecordEventRequest):
    owner_id = request.state.owner_id
    thread_id = str(body.thread_id)
    with session() as s:
        thread = s.get(Thread, thread_id)
        if thread is None or thread.owner_id != owner_id:
            return semantic_validation_error("unknown thread")
    # Events are free and never advance the epoch (spec/03).
    return {"tags": []}


@router.post("/v1/turn-taking/actions/respond")
async def respond(request: Request, body: RespondRequest):
    owner_id = request.state.owner_id
    thread_id = str(body.thread_id)
    async with _thread_locks[thread_id]:
        with session() as s:
            thread = s.get(Thread, thread_id)
            if thread is None or thread.owner_id != owner_id:
                return semantic_validation_error("unknown thread")
            # Epoch check precedes model work and billing (spec/05).
            if body.turn_epoch != thread.turn_epoch:
                metrics.record_epoch_supersession()
                return {"scheduled": [], "superseded": True}

            reservations = []
            try:
                reservations.append(billing.reserve(owner_id, "turn-taking"))
                reservations.append(billing.reserve(owner_id, "theoryofmind"))
            except billing.InsufficientCredits:
                for r in reservations:
                    billing.release(r)
                return payment_required()

            recent = s.query(ThreadMessage).filter(
                ThreadMessage.thread_id == thread_id
            ).order_by(ThreadMessage.id.desc()).limit(20).all()
            transcript = [
                {"sender": m.sender, "content": m.content} for m in reversed(recent)
            ]
            recalled = _recalled_context(owner_id, thread, transcript) if thread.memory_bank_id else ""
            from .social_learning import latest_prompt_block
            refinement = refine(
                body.content, transcript=transcript, recalled_context=recalled,
                system_prompt=body.system_prompt, agent_name=body.agent_name,
                learned_prompt_block=latest_prompt_block(owner_id))
            s.add(RouterTrace(
                thread_id=thread_id, owner_id=owner_id, epoch=thread.turn_epoch,
                decision="respond", scores_json=dumps({
                    "mental_state": refinement.mental_state,
                    "rationale": refinement.rationale,
                }), created_at=utcnow()))
            bubbles = naturalize(refinement.refined)
            reading_delay_ms, typing_wpm, max_typing_ms = resolve_pacing(
                body.pacing.model_dump() if body.pacing else None)

            reply_group = new_uuid()
            metadata = body.metadata  # deeply echoed; null when omitted
            entries = []
            created_stamps = [utcnow() for _ in bubbles]
            delivery = deliver_times(
                bubbles, created_stamps[0] if created_stamps else utcnow(),
                reading_delay_ms, typing_wpm, max_typing_ms)
            for position, content in enumerate(bubbles):
                stamp = created_stamps[position]
                row = Schedule(
                    id=new_uuid(), thread_id=thread_id, owner_id=owner_id,
                    reply_group=reply_group, position=position, content=content,
                    deliver_at=delivery[position], status="scheduled",
                    metadata_json=dumps(metadata) if metadata is not None else None,
                    created_at=stamp, updated_at=stamp)
                s.add(row)
                entries.append({
                    "id": row.id,
                    "content": content,
                    "position": position,
                    "deliver_at": delivery[position],
                    "metadata": metadata,
                })
            scheduled = [{
                "id": e["id"],
                "thread_id": thread_id,
                "content": e["content"],
                "position": e["position"],
                "deliver_at": ts(e["deliver_at"]),
                "status": "scheduled",
                "created_at": ts(created_stamps[e["position"]]),
                "updated_at": ts(created_stamps[e["position"]]),
            } for e in entries]
            outbox_row = None
            if entries:
                # Outbox committed in the same transaction as the schedules so
                # delivery publication cannot be lost between DB commit and
                # scheduler arming (spec/06 §Command transaction).
                outbox_row = Outbox(
                    kind="deliver_reply",
                    payload_json=dumps({
                        "reply_group": reply_group,
                        "thread_id": thread_id,
                        "channel": _channel(thread_id),
                    }),
                    created_at=utcnow())
                s.add(outbox_row)
                s.flush()
                outbox_id = outbox_row.id

        for r in reservations:
            billing.capture(r)
        if entries:
            scheduler.schedule_group(_channel(thread_id), thread_id, entries)
            with session() as s2:
                row = s2.get(Outbox, outbox_id)
                if row is not None:
                    row.processed_at = utcnow()
    return {"scheduled": scheduled, "superseded": False}
