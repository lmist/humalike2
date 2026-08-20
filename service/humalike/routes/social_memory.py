"""Social Memory routes (spec/03 §Social Memory).

Ingest is free and first-write-wins under an owner-wide Idempotency-Key;
recall and ask are billable social-memory commands.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from .. import billing
from ..db import session
from ..engine import memory as memory_engine
from ..errors import payment_required
from ..schemas.realtime import AskRequest, IngestRequest, RecallRequest
from ..storage import IdempotencyRecord, dumps, loads
from ..timefmt import utcnow

router = APIRouter()


@router.post("/v1/social-memory/actions/ingest")
async def ingest(request: Request, body: IngestRequest):
    owner_id = request.state.owner_id
    key = request.headers.get("idempotency-key")
    if key:
        with session() as s:
            record = s.get(IdempotencyRecord, (owner_id, key))
            if record is not None:
                # Owner-wide first-write-wins: identical, changed-body, and
                # different-scope replays all return the first response and
                # store nothing (spec/02 §Idempotency and concurrency).
                return loads(record.response_json)
    count = memory_engine.ingest(
        owner_id, body.scope_id,
        [m.model_dump() for m in body.transcript])
    response = {"ingested": count}
    if key:
        with session() as s:
            if s.get(IdempotencyRecord, (owner_id, key)) is None:
                s.add(IdempotencyRecord(
                    owner_id=owner_id, key=key,
                    response_json=dumps(response), created_at=utcnow()))
    return response


@router.post("/v1/social-memory/actions/recall")
async def recall(request: Request, body: RecallRequest):
    owner_id = request.state.owner_id
    try:
        billing.bill(owner_id, "social-memory")
    except billing.InsufficientCredits:
        return payment_required()
    context = memory_engine.recall(
        owner_id, body.scope_id, body.message.speaker, body.message.text)
    return {"context": context}


@router.post("/v1/social-memory/actions/ask")
async def ask(request: Request, body: AskRequest):
    owner_id = request.state.owner_id
    try:
        billing.bill(owner_id, "social-memory")
    except billing.InsufficientCredits:
        return payment_required()
    answer = memory_engine.ask(owner_id, body.scope_id, body.question)
    return {"answer": answer}
