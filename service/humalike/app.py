"""Application assembly. HTTP and WSS share one deployment (ADR hum-y36v)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .auth import seed_keys
from .billing import reconcile_abandoned
from .db import create_all
from .errors import install_error_handlers
from .jobs import start_workers
from .middleware import GatewayMiddleware
from .scheduler import scheduler
from .routes import (
    credits,
    foresee,
    internal,
    observability,
    personas,
    social_learning,
    social_memory,
    turn_taking,
    ws,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    seed_keys()
    reconcile_abandoned()
    scheduler.recover()
    workers = start_workers()
    yield
    for task in workers:
        task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Humalike API recreation",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    install_error_handlers(app)
    app.add_middleware(GatewayMiddleware)
    for module in (credits, turn_taking, social_memory, social_learning,
                   foresee, observability, personas, ws, internal):
        app.include_router(module.router)
    return app


app = create_app()
