"""Social Learning routes (spec/04 §Social Learning).

Learned style is persisted separately from durable factual memory
(spec/05 §Social Learning; bead hum-paj1) so later turns can inject the
current prompt block over a bounded recent window (hum-35fr).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from .. import billing
from ..db import session
from ..engine.learning import extract
from ..errors import payment_required
from ..schemas.intelligence import ExtractRequest
from ..storage import LearnedProfile, dumps
from ..timefmt import utcnow

router = APIRouter()

# Bounded refresh window: keep only the newest profiles per owner.
PROFILE_WINDOW = 5


def latest_prompt_block(owner_id: str) -> str:
    """Most recent learned prompt block for an owner ("" when none)."""
    with session() as s:
        row = s.execute(
            select(LearnedProfile)
            .where(LearnedProfile.owner_id == owner_id)
            .order_by(LearnedProfile.id.desc()).limit(1)
        ).scalar_one_or_none()
        return row.prompt_block if row is not None else ""


@router.post("/v1/social-learning/actions/extract")
async def extract_profile(request: Request, body: ExtractRequest):
    owner_id = request.state.owner_id
    try:
        billing.bill(owner_id, "social-learning")
    except billing.InsufficientCredits:
        return payment_required()
    source = body.transcript.source if body.transcript.source is not None else ""
    messages = [m.model_dump() for m in body.transcript.messages]
    result = extract(messages, source)
    with session() as s:
        s.add(LearnedProfile(
            owner_id=owner_id, source=source,
            profile_json=dumps(result["profile"]),
            prompt_block=result["prompt_block"], created_at=utcnow()))
        old = s.execute(
            select(LearnedProfile)
            .where(LearnedProfile.owner_id == owner_id)
            .order_by(LearnedProfile.id.desc()).offset(PROFILE_WINDOW)
        ).scalars().all()
        for row in old:
            s.delete(row)
    return result
