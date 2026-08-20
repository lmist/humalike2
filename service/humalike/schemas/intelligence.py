"""Request models for Social Learning and Theory of Mind (spec/04).

Unknown request fields, top-level or nested, are silently ignored — the
Pydantic default (spec/02 §HTTP and serialization). Constraint types map to
the tested 422 vocabulary: missing, too_short.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TranscriptMessage(BaseModel):
    id: str
    speaker: str
    text: str
    user_id: str | None = None
    channel: str | None = None
    timestamp: str | None = None
    reply_to: str | None = None


class Transcript(BaseModel):
    messages: list[TranscriptMessage] = Field(min_length=1)
    source: str | None = None


class ExtractRequest(BaseModel):
    transcript: Transcript


class ForeseeTurn(BaseModel):
    speaker: str
    text: str


class ForeseeRequest(BaseModel):
    transcript: list[ForeseeTurn] = Field(min_length=1)
    candidate_reply: str
    agent_name: str | None = None
    system_prompt: str | None = None
    subject_name: str | None = None
