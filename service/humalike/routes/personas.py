"""Persona routes (spec/04): generate, enhance, validate, and the Population,
Enhancement, and Evaluation repositories.

Actions bill the "personas" component once and enqueue a Job; repository GETs
are free projections (terminal re-polling changes calls/credits by zero).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import billing, jobs
from ..db import session
from ..engine import personas as engine
from ..errors import error_response, invalid_id, payment_required
from ..ids import new_uuid
from ..schemas.personas import EnhanceRequest, GenerateRequest, ValidateRequest
from ..storage import Job, dumps
from ..timefmt import utcnow

router = APIRouter()

jobs.register_handler("population", engine.run_population)
jobs.register_handler("enhancement", engine.run_enhancement)
jobs.register_handler("evaluation", engine.run_evaluation)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_REPOSITORY_KINDS = {
    "Population": "population",
    "Enhancement": "enhancement",
    "Evaluation": "evaluation",
}


def _enqueue(owner_id: str, kind: str, request_payload: dict) -> dict:
    now = utcnow()
    job_id = new_uuid()
    with session() as s:
        s.add(Job(
            id=job_id, owner_id=owner_id, kind=kind, status="pending",
            progress_json=None, request_json=dumps(request_payload),
            result_json=None, error_json=None, lease_until=None,
            created_at=now, updated_at=now,
        ))
    return {"id": job_id, "status": "pending"}


@router.post("/v1/personas/actions/generate")
async def generate(request: Request, body: GenerateRequest):
    try:
        billing.bill(request.state.owner_id, "personas")
    except billing.InsufficientCredits:
        return payment_required()
    return _enqueue(request.state.owner_id, "population", {
        "prompt": body.prompt, "count": body.count, "grounding": body.grounding,
    })


@router.post("/v1/personas/actions/enhance")
async def enhance(request: Request, body: EnhanceRequest):
    try:
        billing.bill(request.state.owner_id, "personas")
    except billing.InsufficientCredits:
        return payment_required()
    return _enqueue(request.state.owner_id, "enhancement", {
        "persona": body.persona, "grounding": body.grounding,
    })


@router.post("/v1/personas/actions/validate")
async def validate(request: Request, body: ValidateRequest):
    try:
        billing.bill(request.state.owner_id, "personas")
    except billing.InsufficientCredits:
        return payment_required()
    blueprint = None if body.blueprint is None else engine.normalize_blueprint(body.blueprint)
    return _enqueue(request.state.owner_id, "evaluation", {
        "personas": [persona.model_dump() for persona in body.personas],
        "blueprint": blueprint,
    })


@router.get("/v1/personas/repositories/{repository}/by-id/{resource_id}")
async def repository_get(request: Request, repository: str, resource_id: str):
    kind = _REPOSITORY_KINDS.get(repository)
    if kind is None:
        return error_response(404, "NOT_FOUND", "unknown repository")
    if not _UUID_RE.match(resource_id):
        return invalid_id()
    with session() as s:
        job = s.get(Job, resource_id.lower())
    if job is None or job.owner_id != request.state.owner_id or job.kind != kind:
        return JSONResponse(content=None)
    return JSONResponse(content=engine.resource_view(job))
