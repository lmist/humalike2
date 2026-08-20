"""Theory-of-Mind foresee route (spec/04 §Theory of Mind)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from .. import billing
from ..engine.foresee import foresee
from ..errors import payment_required
from ..schemas.intelligence import ForeseeRequest

router = APIRouter()


@router.post("/v1/foresee/actions/foresee")
async def foresee_action(request: Request, body: ForeseeRequest):
    owner_id = request.state.owner_id
    try:
        billing.bill(owner_id, "theoryofmind")
    except billing.InsufficientCredits:
        return payment_required()
    return foresee(
        [t.model_dump() for t in body.transcript],
        body.candidate_reply,
        agent_name=body.agent_name,
        system_prompt=body.system_prompt,
        subject_name=body.subject_name,
    )
