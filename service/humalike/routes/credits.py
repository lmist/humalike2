"""Identity and usage routes (spec/03 §Identity and usage). Both are free."""

from __future__ import annotations

from fastapi import APIRouter, Request

from .. import billing

router = APIRouter()


@router.post("/v1/turn-taking/actions/whoami")
async def whoami(request: Request) -> dict:
    return {"user_id": request.state.owner_id}


@router.post("/v1/credits/projections/usage-summary")
async def usage_summary(request: Request) -> dict:
    return billing.usage_summary(request.state.owner_id)
