"""Entry point: python -m humalike.main (or uvicorn humalike.app:app)."""

from __future__ import annotations

import os

import uvicorn


def run() -> None:
    uvicorn.run(
        "humalike.app:app",
        host=os.environ.get("HUMALIKE_HOST", "127.0.0.1"),
        port=int(os.environ.get("HUMALIKE_PORT", "8080")),
        log_level=os.environ.get("HUMALIKE_LOG_LEVEL", "warning"),
    )


if __name__ == "__main__":
    run()
