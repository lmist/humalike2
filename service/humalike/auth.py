"""Bearer authentication and hashed key store (spec/02 §Authentication).

Keys are stored as HMAC-SHA256 lookup values and never logged. Every public
route requires Authorization: Bearer <token>; failures return the exact
tested 401 body.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from sqlalchemy import select

from .config import settings
from .db import session
from .storage import ApiKey, Owner
from .timefmt import utcnow


def key_hmac(plain: str) -> str:
    return hmac.new(settings.secret.encode(), plain.encode(), hashlib.sha256).hexdigest()


def seed_keys() -> None:
    """Register configured plaintext keys (hashed) with funded owners."""
    keys = [k.strip() for k in settings.seed_keys.split(",") if k.strip()]
    if not keys:
        return
    with session() as s:
        for plain in keys:
            digest = key_hmac(plain)
            existing = s.execute(select(ApiKey).where(ApiKey.key_hmac == digest)).scalar_one_or_none()
            if existing:
                continue
            owner_id = "own_" + hashlib.sha256(digest.encode()).hexdigest()[:24]
            if s.get(Owner, owner_id) is None:
                s.add(Owner(id=owner_id, credits_balance=settings.initial_credits, created_at=utcnow()))
            s.add(ApiKey(key_hmac=digest, owner_id=owner_id, created_at=utcnow()))


def mint_key() -> str:
    """Create and register a fresh funded key (operator utility)."""
    plain = "ak_" + secrets.token_urlsafe(24)
    with session() as s:
        digest = key_hmac(plain)
        owner_id = "own_" + hashlib.sha256(digest.encode()).hexdigest()[:24]
        s.add(Owner(id=owner_id, credits_balance=settings.initial_credits, created_at=utcnow()))
        s.add(ApiKey(key_hmac=digest, owner_id=owner_id, created_at=utcnow()))
    return plain


def resolve_bearer(authorization: str | None) -> str | None:
    """Return the owner id for a valid bearer header, else None."""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer" or not parts[1].strip():
        return None
    digest = key_hmac(parts[1].strip())
    with session() as s:
        row = s.execute(select(ApiKey).where(ApiKey.key_hmac == digest)).scalar_one_or_none()
        return row.owner_id if row else None
