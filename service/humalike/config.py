"""Runtime configuration.

Every unknown production behavior stays configuration per spec/08: nothing
here may be represented as established production behavior.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


@dataclass
class Settings:
    # Origin is configurable and defaults to production per spec/02.
    origin: str = os.environ.get("HUMALIKE_ORIGIN", "https://api.humalike.com")
    database_url: str = os.environ.get("HUMALIKE_DATABASE_URL", "sqlite:///./humalike.db")
    # HMAC secret for WSS grants and key hashing. Must be overridden in prod.
    secret: str = os.environ.get("HUMALIKE_SECRET", "humalike-recreation-dev-secret")
    # Comma-separated plaintext API keys seeded at boot (hashed before storage).
    seed_keys: str = os.environ.get("HUMALIKE_SEED_KEYS", "")
    grant_ttl_seconds: float = float(os.environ.get("HUMALIKE_GRANT_TTL", "30.0"))
    # Credit prices per billable component call (configuration, not contract).
    prices: dict[str, int] = field(default_factory=lambda: {
        "turn-taking": _int("HUMALIKE_PRICE_TURN_TAKING", 1),
        "theoryofmind": _int("HUMALIKE_PRICE_THEORYOFMIND", 4),
        "social-memory": _int("HUMALIKE_PRICE_SOCIAL_MEMORY", 1),
        "social-learning": _int("HUMALIKE_PRICE_SOCIAL_LEARNING", 15),
        "social-observability": _int("HUMALIKE_PRICE_SOCIAL_OBSERVABILITY", 11),
        "personas": _int("HUMALIKE_PRICE_PERSONAS", 85),
    })
    # Initial credit balance granted to seeded keys (402 handling is a
    # documented default, not live-proven; see spec/02).
    initial_credits: int = _int("HUMALIKE_INITIAL_CREDITS", 1_000_000)


settings = Settings()
