"""Request models for realtime and memory routes (spec/03).

Unknown request fields, top-level or nested, are silently ignored — the
Pydantic default (spec/02 §HTTP and serialization). Constraint types map to
the tested 422 vocabulary: uuid_parsing, too_short, too_long,
string_too_long, string_too_short, literal_error, missing.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SocialSignalsIntegration(BaseModel):
    scope_id: str | None = None
    channel_id: str | None = None


class SocialMemoryIntegration(BaseModel):
    memory_bank_id: str


class Integrations(BaseModel):
    social_signals: SocialSignalsIntegration | None = None
    social_memory: SocialMemoryIntegration | None = None


class OpenThreadRequest(BaseModel):
    thread_id: UUID | None = None
    integrations: Integrations | None = None


class InboundMessage(BaseModel):
    sender: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=4000)
    client_ts: str | None = None
    has_media: bool = False


class SubmitRequest(BaseModel):
    thread_id: UUID
    messages: list[InboundMessage] = Field(min_length=1, max_length=20)
    system_prompt: str | None = None
    skip_decide: bool = False


class RecordEventRequest(BaseModel):
    thread_id: UUID
    type: Literal["typing_start", "typing_stop", "message_edited"]
    sender: str
    client_ts: str | None = None


class Pacing(BaseModel):
    reading_delay_ms: float | None = None
    typing_wpm: float | None = None
    max_typing_ms: float | None = None


class RespondRequest(BaseModel):
    thread_id: UUID
    content: str
    turn_epoch: int
    system_prompt: str | None = None
    agent_name: str | None = None
    pacing: Pacing | None = None
    metadata: dict[str, Any] | None = None


class MemoryMessageIn(BaseModel):
    speaker: str
    text: str


class IngestRequest(BaseModel):
    scope_id: str
    transcript: list[MemoryMessageIn] = Field(min_length=1)


class RecallRequest(BaseModel):
    scope_id: str
    message: MemoryMessageIn


class AskRequest(BaseModel):
    scope_id: str
    question: str = Field(min_length=1)
