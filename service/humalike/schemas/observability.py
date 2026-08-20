"""Request models for Social Observability and full audits."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class ObservabilityMessage(BaseModel):
    id: str
    speaker: str
    text: str
    user_id: str | None = None
    channel: str | None = None
    timestamp: str | None = None
    reply_to: str | None = None


class ObservabilityTranscript(BaseModel):
    messages: list[ObservabilityMessage] = Field(min_length=1)
    source: str | None = None


class AnalyzeRequest(BaseModel):
    agent_name: str
    transcript: ObservabilityTranscript
    focus: str | None = None


class AuditPrepareRequest(BaseModel):
    raw_text: str = Field(min_length=1, max_length=300_000)


class AuditLaunchRequest(BaseModel):
    run_id: UUID
    agent_name: str


class AuditProjectionRequest(BaseModel):
    run_id: UUID
