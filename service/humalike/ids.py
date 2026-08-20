"""Identifier generation."""

from __future__ import annotations

import secrets
import uuid


def new_uuid() -> str:
    return str(uuid.uuid4())


def event_id() -> str:
    """WSS event envelope id: evt_ + 32 lowercase hex."""
    return "evt_" + secrets.token_hex(16)


def request_id() -> str:
    return "req_" + secrets.token_hex(16)
