"""Gateway middleware (spec/06 §Command transaction).

Authenticates, assigns a non-empty x-request-id to every HTTP response
(success and error alike), keeps every body application/json, and never
emits rate-limit or Retry-After headers. Bearer values are never logged.
"""

from __future__ import annotations

import json
import time

from . import metrics
from .auth import resolve_bearer
from .billing import count_request
from .errors import error_body
from .ids import request_id

_EXEMPT_PREFIXES = ("/v1/ws/",)


class GatewayMiddleware:
    """Pure ASGI so the request-id header covers every response path."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = request_id()
        started = time.monotonic()
        status_seen = {"status": 0}

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                status_seen["status"] = message.get("status", 0)
                headers = [
                    (name, value) for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", rid.encode()))
                message = {**message, "headers": headers}
            await send(message)

        path = scope.get("path", "")
        if path.startswith("/v1/") and not any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            authorization = None
            for name, value in scope.get("headers", []):
                if name == b"authorization":
                    authorization = value.decode("latin-1")
                    break
            owner_id = resolve_bearer(authorization)
            if owner_id is None:
                body = json.dumps(
                    error_body("UNAUTHORIZED", "missing or invalid credentials"),
                    separators=(",", ":")).encode()
                await send_with_request_id({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                })
                await send({"type": "http.response.body", "body": body})
                return
            state = scope.setdefault("state", {})
            state["owner_id"] = owner_id
            count_request(owner_id)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            body = json.dumps(
                error_body("INTERNAL", "internal error"),
                separators=(",", ":")).encode()
            await send_with_request_id({
                "type": "http.response.start",
                "status": 500,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": body})
        finally:
            metrics.record_request(
                path, scope.get("method", "GET"), status_seen["status"],
                (time.monotonic() - started) * 1000.0)
