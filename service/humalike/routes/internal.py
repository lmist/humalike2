"""Internal operator surface: metrics scrape and liveness.

Deliberately **not** under ``/v1``. The public contract is exactly the routes
in spec/03 and spec/04; adding an authenticated public metrics route would
invent surface production does not expose, and mounting it under ``/v1`` would
put it behind the gateway's bearer check (spec/02 §Authentication) where a
Prometheus scraper cannot reach it. ``/internal/*`` is expected to be bound to
an operator-only network or blocked at the ingress, exactly like a sidecar
admin port.

Nothing here reads owner data: the registry holds counts, latencies, and
label values (route names, components, close codes) only — never transcript
bodies, bearer values, WSS grants, or account ids (spec/06 §Security).

Self-contained: this router is not wired into ``create_app`` here. The lead
adds ``internal`` to the router list in ``humalike/app.py`` when the surface
is switched on.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from .. import metrics

router = APIRouter()


@router.get("/internal/metrics")
async def internal_metrics() -> dict:
    """The whole in-process registry as JSON (docs/dashboards/README.md)."""
    return metrics.snapshot()


@router.get("/internal/metrics/prometheus", response_class=PlainTextResponse)
async def internal_metrics_prometheus() -> PlainTextResponse:
    """The same series in Prometheus text exposition format for scraping."""
    return PlainTextResponse(
        metrics.prometheus_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/internal/healthz")
async def internal_healthz() -> dict:
    """Liveness only. Readiness would have to prove database and worker health,
    which belongs to the deployment's own probe, not to this contract."""
    return {"status": "ok"}
