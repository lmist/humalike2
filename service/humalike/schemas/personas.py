"""Persona action request models (spec/04 §Persona generation/enhancement/validation).

Unknown fields are ignored everywhere. The blueprint is accepted as a plain
mapping so the submitted values (including nested distributions and
conditionals) can be echoed verbatim after normalization.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Grounding = Literal["off", "web", "research"]


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt: str = Field(min_length=1)
    count: int = Field(ge=1)
    grounding: Grounding = "off"


class EnhanceRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    persona: str = Field(min_length=1)
    grounding: Grounding = "off"


class PersonaIn(BaseModel):
    """Validation input persona; only persona_id is required (spec/04)."""

    model_config = ConfigDict(extra="ignore")
    persona_id: str
    fields: dict[str, str] = Field(default_factory=dict)
    system_prompt: str = ""
    markdown: str = ""


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    personas: list[PersonaIn] = Field(min_length=1)
    blueprint: dict[str, Any] | None = None
