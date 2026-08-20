"""Social Observability analyze, Report repository, and full-audit routes."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from sqlalchemy import select

from .. import billing
from ..db import session
from ..engine import audit as audit_engine
from ..engine.observability import build_report
from ..errors import (
    invalid_id,
    payment_required,
    semantic_validation_error,
)
from ..jobs import register_handler
from ..schemas.observability import (
    AnalyzeRequest,
    AuditLaunchRequest,
    AuditPrepareRequest,
    AuditProjectionRequest,
)
from ..storage import AuditRun, StoredReport, Job, dumps, loads
from ..timefmt import utcnow

router = APIRouter()


def _bill(owner_id: str):
    try:
        billing.bill(owner_id, "social-observability")
    except billing.InsufficientCredits:
        return payment_required()
    return None


def _unknown_run():
    return semantic_validation_error(
        "unknown run",
        [{"field": "run_id", "message": "no such run"}],
    )


@router.post("/v1/social-observability/actions/analyze")
async def analyze(request: Request, body: AnalyzeRequest):
    owner_id = request.state.owner_id
    payment_error = _bill(owner_id)
    if payment_error is not None:
        return payment_error
    report = build_report(
        [message.model_dump() for message in body.transcript.messages],
        body.agent_name,
        body.focus,
        user_id_mode="echo",
    )
    with session() as s:
        s.add(StoredReport(
            id=str(uuid4()),
            owner_id=owner_id,
            report_json=dumps(report),
            created_at=utcnow(),
        ))
    return report


@router.get("/v1/social-observability/repositories/Report/by-id/{report_id}")
async def report_by_id(request: Request, report_id: str):
    try:
        parsed = UUID(report_id)
    except (ValueError, AttributeError):
        return invalid_id()
    if parsed.version is None or not 1 <= parsed.version <= 8:
        return invalid_id()
    with session() as s:
        report = s.execute(
            select(StoredReport).where(
                StoredReport.id == str(parsed),
                StoredReport.owner_id == request.state.owner_id,
            )
        ).scalar_one_or_none()
        return loads(report.report_json) if report is not None else None


@router.post("/v1/social-observability/actions/audit_prepare")
async def audit_prepare(request: Request, body: AuditPrepareRequest):
    owner_id = request.state.owner_id
    payment_error = _bill(owner_id)
    if payment_error is not None:
        return payment_error

    token_count = audit_engine.estimated_tokens(body.raw_text)
    if token_count > 32_768:
        return semantic_validation_error(
            "This paste is too large to read: "
            f"about {token_count:,} tokens, and the audit accepts about 32,768. "
            "Send at most 250 messages.",
            [{"field": "raw_text", "message": "at most ~32768 tokens allowed"}],
        )

    messages = audit_engine.parse_raw_text(body.raw_text)
    if not messages:
        return semantic_validation_error(
            "no messages could be read from this text",
            [{"field": "raw_text", "message": "no messages detected"}],
        )
    if len(messages) > 250:
        return semantic_validation_error(
            f"This transcript has {len(messages)} messages; "
            "the audit accepts at most 250.",
            [{"field": "raw_text", "message": "over the 250-message cap"}],
        )

    names = audit_engine.participants(messages)
    agent_guess = audit_engine.guess_agent(names)
    run_id = str(uuid4())
    now = utcnow()
    with session() as s:
        s.add(AuditRun(
            run_id=run_id,
            owner_id=owner_id,
            agent_name=agent_guess or "",
            agent_guess=agent_guess,
            launched=False,
            status="prepared",
            transcript_json=dumps({"messages": messages, "source": None}),
            report_json=None,
            read_json=None,
            verdicts_json=None,
            replies_json=None,
            created_at=now,
            updated_at=now,
        ))
    return {
        "run_id": run_id,
        "messages": len(messages),
        "participants": names,
        "agent_guess": agent_guess,
    }


@router.post("/v1/social-observability/actions/audit_launch")
async def audit_launch(request: Request, body: AuditLaunchRequest):
    owner_id = request.state.owner_id
    run_id = str(body.run_id)
    with session() as s:
        run = s.execute(
            select(AuditRun).where(
                AuditRun.run_id == run_id,
                AuditRun.owner_id == owner_id,
            )
        ).scalar_one_or_none()
        if run is None:
            return _unknown_run()

        if run.launched:
            return {
                "run_id": run_id,
                "agent_name": run.agent_name,
                "status": "completed" if run.status == "completed" else "queued",
            }

        transcript = loads(run.transcript_json)
        names = audit_engine.participants(transcript["messages"])
        if body.agent_name not in names:
            return semantic_validation_error(
                "agent_name must be one of the transcript's speakers",
                [{
                    "field": "agent_name",
                    "message": f"'{body.agent_name}' never speaks",
                }],
            )

    payment_error = _bill(owner_id)
    if payment_error is not None:
        return payment_error

    with session() as s:
        run = s.get(AuditRun, run_id)
        now = utcnow()
        job_id = str(uuid4())
        run.agent_name = body.agent_name
        run.launched = True
        run.status = "queued"
        run.updated_at = now
        s.add(Job(
            id=job_id,
            owner_id=owner_id,
            kind="audit",
            status="pending",
            progress_json=None,
            request_json=dumps({"run_id": run_id}),
            result_json=None,
            error_json=None,
            lease_until=None,
            created_at=now,
            updated_at=now,
        ))
    return {"run_id": run_id, "agent_name": body.agent_name, "status": "queued"}


@router.post("/v1/social-observability/projections/audit-run")
async def audit_projection(request: Request, body: AuditProjectionRequest):
    run_id = str(body.run_id)
    with session() as s:
        run = s.execute(
            select(AuditRun).where(
                AuditRun.run_id == run_id,
                AuditRun.owner_id == request.state.owner_id,
            )
        ).scalar_one_or_none()
        if run is None:
            return _unknown_run()
        return {
            "run_id": run_id,
            "agent_name": run.agent_name if run.launched else run.agent_guess,
            "transcript": loads(run.transcript_json),
            "report": loads(run.report_json),
            "read": loads(run.read_json),
            "verdicts": loads(run.verdicts_json),
            "replies": loads(run.replies_json) or [],
        }


async def _run_audit(job_id: str) -> None:
    with session() as s:
        job = s.get(Job, job_id)
        if job is None:
            return
        run_id = loads(job.request_json)["run_id"]
        run = s.get(AuditRun, run_id)
        if run is None:
            return
        transcript = loads(run.transcript_json)
        messages = transcript["messages"]
        agent_name = run.agent_name
        needs_report = run.report_json is None

    if needs_report:
        report = build_report(
            messages,
            agent_name,
            user_id_mode="null",
        )
        with session() as s:
            run = s.get(AuditRun, run_id)
            if run.report_json is None:
                run.report_json = dumps(report)
                run.updated_at = utcnow()
        await asyncio.sleep(0.15)

    with session() as s:
        run = s.get(AuditRun, run_id)
        needs_read = run.read_json is None
    if needs_read:
        read = audit_engine.build_read(messages, agent_name)
        with session() as s:
            run = s.get(AuditRun, run_id)
            if run.read_json is None:
                run.read_json = dumps(read)
                run.updated_at = utcnow()
        await asyncio.sleep(0.15)

    with session() as s:
        run = s.get(AuditRun, run_id)
        needs_verdicts = run.verdicts_json is None
    if needs_verdicts:
        verdicts = audit_engine.build_verdicts(messages, agent_name)
        with session() as s:
            run = s.get(AuditRun, run_id)
            if run.verdicts_json is None:
                run.verdicts_json = dumps(verdicts)
                run.updated_at = utcnow()
        await asyncio.sleep(0.15)
    else:
        with session() as s:
            verdicts = loads(s.get(AuditRun, run_id).verdicts_json)

    with session() as s:
        run = s.get(AuditRun, run_id)
        if run.replies_json is None:
            run.replies_json = dumps(audit_engine.build_replies(verdicts))
        run.status = "completed"
        run.updated_at = utcnow()
        job = s.get(Job, job_id)
        if job is not None:
            job.status = "succeeded"
            job.result_json = dumps({"run_id": run_id})
            job.lease_until = None
            job.updated_at = utcnow()


register_handler("audit", _run_audit)
