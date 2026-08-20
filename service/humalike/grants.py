"""WSS grant issuer/validator (spec/02 §WebSocket protocol).

Grant: wss://<origin-host>/v1/ws/turn-taking-thread?token=<payload>.<signature>
with exactly one query parameter, two base64url segments, a 43-character
HMAC-SHA256-sized signature, and a 30.0s TTL.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone

from .config import settings
from .timefmt import utcnow


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(payload_segment: str) -> str:
    digest = hmac.new(settings.secret.encode(), payload_segment.encode(), hashlib.sha256).digest()
    return _b64url(digest)  # 32 bytes -> 43 base64url chars


def issue(owner_id: str, thread_id: str, channel: str) -> tuple[str, datetime]:
    """Return (token, expires_at)."""
    expires_at = utcnow() + timedelta(seconds=settings.grant_ttl_seconds)
    payload = {
        "o": owner_id,
        "t": thread_id,
        "c": channel,
        "exp": expires_at.timestamp(),
        "n": secrets.token_hex(8),
    }
    payload_segment = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    return f"{payload_segment}.{_sign(payload_segment)}", expires_at


def validate(token: str) -> dict | None:
    """Return the grant payload if the signature is valid and unexpired."""
    parts = token.split(".")
    if len(parts) != 2:
        return None
    payload_segment, signature = parts
    if not hmac.compare_digest(_sign(payload_segment), signature):
        return None
    try:
        payload = json.loads(_b64url_decode(payload_segment))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    if datetime.fromtimestamp(exp, tz=timezone.utc) < utcnow():
        return None
    return payload
