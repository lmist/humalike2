"""Social Learning routes (spec/04 §Social Learning)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from .. import billing
from ..engine.learning import extract
from ..errors import payment_required
from ..schemas.intelligence import ExtractRequest

router = APIRouter()


@router.post("/v1/social-learning/actions/extract")
async def extract_profile(request: Request, body: ExtractRequest):
    owner_id = request.state.owner_id
    try:
        billing.bill(owner_id, "social-learning")
    except billing.InsufficientCredits:
        return payment_required()
    source = body.transcript.source if body.transcript.source is not None else ""
    messages = [m.model_dump() for m in body.transcript.messages]
    return extract(messages, source)
