"""Route-specific error serializers (spec/02 §Error shapes are route-specific).

There is no single production error schema beyond the outer
{error:{code,message,details?}} shape; the outer object has exactly one key.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def error_body(code: str, message: str, details: Any | None = None) -> dict:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def error_response(status: int, code: str, message: str, details: Any | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=error_body(code, message, details))


def unauthorized() -> JSONResponse:
    """Exact tested 401 body on every route (spec/02 §Authentication)."""
    return error_response(401, "UNAUTHORIZED", "missing or invalid credentials")


def payment_required() -> JSONResponse:
    """Documented default, not live-proven (spec/02 §Billing)."""
    return error_response(402, "PAYMENT_REQUIRED", "insufficient credits")


def forbidden() -> JSONResponse:
    """Documented default, not live-proven."""
    return error_response(403, "forbidden", "forbidden")


def invalid_id() -> JSONResponse:
    """Malformed id on any repository by-id route: exactly this body, no details."""
    return error_response(400, "VALIDATION_ERROR", "invalid id")


def semantic_validation_error(message: str, details: list[dict[str, str]] | None = None) -> JSONResponse:
    return error_response(400, "VALIDATION_ERROR", message, details)


def upstream_error() -> JSONResponse:
    """Documented default, not live-proven."""
    return error_response(502, "UPSTREAM_ERROR", "upstream error")


def _strip_body_prefix(loc: tuple) -> list:
    """details[].loc MUST NOT carry a leading "body" segment (spec/02)."""
    items = list(loc)
    if items and items[0] == "body":
        items = items[1:]
    return items


def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = []
    for err in exc.errors():
        details.append({
            "loc": _strip_body_prefix(tuple(err.get("loc", ()))),
            "msg": err.get("msg", "invalid"),
            "type": err.get("type", "value_error"),
        })
    return error_response(422, "validation_failed", "request validation failed", details)


def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Keep the outer envelope shape even for framework-raised errors so every
    # response remains application/json with the one-key error object.
    if isinstance(exc.detail, dict) and set(exc.detail.keys()) == {"error"}:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    code = {401: "UNAUTHORIZED", 402: "PAYMENT_REQUIRED", 403: "forbidden",
            404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "ERROR")
    message = exc.detail if isinstance(exc.detail, str) else "error"
    if exc.status_code == 401:
        return unauthorized()
    return error_response(exc.status_code, code, message)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
