"""In-process metrics registry (spec/06 §Reliability and scaling).

The spec requires tracking request latency, model stage latency/cost, queue
lag, schedule lateness, WSS connections/closes, epoch supersessions,
idempotency replays, credit reservations/captures, and conformance suite
results. This module is the recording surface for exactly those signals and
the vocabulary the dashboards in ``docs/dashboards/`` panel against.

Two deliberate constraints:

* **Import-safe standalone.** Nothing here imports another ``humalike``
  module, opens a database, or starts a task, so ``import humalike.metrics``
  is safe from a migration, a worker, or a test that never builds the app.
* **Never on the public contract.** Recording is best-effort and side-effect
  free from the caller's point of view; a metrics failure must not change a
  response. Instrumentation call sites can therefore be added incrementally
  by wrapping existing code in :func:`timer` or calling the ``record_*``
  helpers, with no change to any tested response shape.

Labels are part of a metric's identity. A metric name plus its label set is
one series, matching the Prometheus data model the Grafana dashboards assume.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator

# Milliseconds. Chosen to straddle the observed envelopes: WSS delivery trails
# deliver_at by 6-251 ms, evaluations finish in ~3.5 s, and population,
# enhancement, and audit work run ~52 s, ~37 s, and ~20 s (spec/06).
DEFAULT_BUCKETS_MS: tuple[float, ...] = (
    1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0,
    1_000.0, 2_500.0, 5_000.0, 10_000.0, 30_000.0, 60_000.0,
)

Labels = dict[str, str]


def _key(name: str, labels: Labels) -> tuple:
    return (name, tuple(sorted(labels.items())))


class Counter:
    """Monotonically increasing total for one name/label combination."""

    __slots__ = ("name", "labels", "value", "_lock")

    def __init__(self, name: str, labels: Labels) -> None:
        self.name = name
        self.labels = labels
        self.value = 0.0
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self.value += amount

    def snapshot(self) -> dict:
        return {"name": self.name, "type": "counter",
                "labels": dict(self.labels), "value": self.value}


class Gauge:
    """A value that can move in both directions (active sockets, balances)."""

    __slots__ = ("name", "labels", "value", "_lock")

    def __init__(self, name: str, labels: Labels) -> None:
        self.name = name
        self.labels = labels
        self.value = 0.0
        self._lock = threading.Lock()

    def set(self, value: float) -> None:
        with self._lock:
            self.value = float(value)

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self.value += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self.value -= amount

    def snapshot(self) -> dict:
        return {"name": self.name, "type": "gauge",
                "labels": dict(self.labels), "value": self.value}


class Histogram:
    """Cumulative bucket histogram plus count/sum/min/max."""

    __slots__ = ("name", "labels", "buckets", "counts", "count", "sum",
                 "min", "max", "_lock")

    def __init__(self, name: str, labels: Labels,
                 buckets: tuple[float, ...] = DEFAULT_BUCKETS_MS) -> None:
        self.name = name
        self.labels = labels
        self.buckets = buckets
        self.counts = [0 for _ in buckets] + [0]  # trailing +Inf bucket
        self.count = 0
        self.sum = 0.0
        self.min: float | None = None
        self.max: float | None = None
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        value = float(value)
        with self._lock:
            placed = False
            for index, edge in enumerate(self.buckets):
                if value <= edge:
                    self.counts[index] += 1
                    placed = True
                    break
            if not placed:
                self.counts[-1] += 1
            self.count += 1
            self.sum += value
            self.min = value if self.min is None else min(self.min, value)
            self.max = value if self.max is None else max(self.max, value)

    def snapshot(self) -> dict:
        with self._lock:
            cumulative = []
            running = 0
            for index, edge in enumerate(self.buckets):
                running += self.counts[index]
                cumulative.append({"le": edge, "count": running})
            cumulative.append({"le": "+Inf", "count": self.count})
            return {
                "name": self.name, "type": "histogram",
                "labels": dict(self.labels),
                "count": self.count, "sum": self.sum,
                "min": self.min, "max": self.max,
                "avg": (self.sum / self.count) if self.count else None,
                "buckets": cumulative,
            }


class Registry:
    """Process-local metric store. Cheap, lock-guarded, never persistent."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple, Counter] = {}
        self._gauges: dict[tuple, Gauge] = {}
        self._histograms: dict[tuple, Histogram] = {}
        self.created_at = time.time()

    def counter(self, name: str, **labels: str) -> Counter:
        key = _key(name, labels)
        with self._lock:
            metric = self._counters.get(key)
            if metric is None:
                metric = self._counters[key] = Counter(name, labels)
        return metric

    def gauge(self, name: str, **labels: str) -> Gauge:
        key = _key(name, labels)
        with self._lock:
            metric = self._gauges.get(key)
            if metric is None:
                metric = self._gauges[key] = Gauge(name, labels)
        return metric

    def histogram(self, name: str, buckets: tuple[float, ...] = DEFAULT_BUCKETS_MS,
                  **labels: str) -> Histogram:
        key = _key(name, labels)
        with self._lock:
            metric = self._histograms.get(key)
            if metric is None:
                metric = self._histograms[key] = Histogram(name, labels, buckets)
        return metric

    def reset(self) -> None:
        """Drop every series. Used by tests, never on a serving path."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self.created_at = time.time()

    def snapshot(self) -> dict:
        with self._lock:
            counters = [m.snapshot() for m in self._counters.values()]
            gauges = [m.snapshot() for m in self._gauges.values()]
            histograms = [m.snapshot() for m in self._histograms.values()]
        return {
            "uptime_seconds": time.time() - self.created_at,
            "counters": sorted(counters, key=lambda m: (m["name"], sorted(m["labels"].items()))),
            "gauges": sorted(gauges, key=lambda m: (m["name"], sorted(m["labels"].items()))),
            "histograms": sorted(histograms, key=lambda m: (m["name"], sorted(m["labels"].items()))),
        }


registry = Registry()


# --------------------------------------------------------------------------
# Metric names. Dashboards reference these strings, so they are the contract
# between service instrumentation and docs/dashboards/*.json.
# --------------------------------------------------------------------------
REQUESTS_TOTAL = "humalike_requests_total"
REQUEST_LATENCY_MS = "humalike_request_latency_ms"
MODEL_STAGE_LATENCY_MS = "humalike_model_stage_latency_ms"
MODEL_STAGE_TOTAL = "humalike_model_stage_total"
QUEUE_LAG_MS = "humalike_queue_lag_ms"
SCHEDULE_LATENESS_MS = "humalike_schedule_lateness_ms"
WS_CONNECTIONS_TOTAL = "humalike_ws_connections_total"
WS_CLOSES_TOTAL = "humalike_ws_closes_total"
WS_CONNECTIONS_ACTIVE = "humalike_ws_connections_active"
WS_FRAMES_TOTAL = "humalike_ws_frames_total"
EPOCH_SUPERSESSIONS_TOTAL = "humalike_epoch_supersessions_total"
EPOCH_ADVANCES_TOTAL = "humalike_epoch_advances_total"
IDEMPOTENCY_REPLAYS_TOTAL = "humalike_idempotency_replays_total"
CREDIT_RESERVATIONS_TOTAL = "humalike_credit_reservations_total"
CREDIT_CAPTURES_TOTAL = "humalike_credit_captures_total"
CREDIT_RELEASES_TOTAL = "humalike_credit_releases_total"
CREDITS_CAPTURED_TOTAL = "humalike_credits_captured_total"
CREDIT_DENIALS_TOTAL = "humalike_credit_denials_total"
JOBS_TOTAL = "humalike_jobs_total"
JOB_DURATION_MS = "humalike_job_duration_ms"
MEMORY_RECALL_HITS_TOTAL = "humalike_memory_recall_hits_total"
CONFORMANCE_ASSERTIONS = "humalike_conformance_assertions"


# --------------------------------------------------------------------------
# Recording helpers. Call sites can be added incrementally; every helper is a
# no-op as far as the caller's control flow is concerned.
# --------------------------------------------------------------------------
def record_request(route: str, method: str, status: int, duration_ms: float) -> None:
    """Phase 0-1: request latency and outcome by route (spec/06)."""
    registry.counter(REQUESTS_TOTAL, route=route, method=method,
                     status=str(status)).inc()
    registry.histogram(REQUEST_LATENCY_MS, route=route, method=method).observe(duration_ms)


def record_model_stage(stage: str, duration_ms: float, outcome: str = "ok") -> None:
    """Phase 3/5/6/7: per-stage model latency (router, tom, naturalizer, ...)."""
    registry.counter(MODEL_STAGE_TOTAL, stage=stage, outcome=outcome).inc()
    registry.histogram(MODEL_STAGE_LATENCY_MS, stage=stage).observe(duration_ms)


def record_queue_lag(queue: str, lag_ms: float) -> None:
    """Phase 6-7: enqueue-to-claim lag for asynchronous audit/persona work."""
    registry.histogram(QUEUE_LAG_MS, queue=queue).observe(lag_ms)


def record_schedule_lateness(lateness_ms: float, thread_partition: str = "all") -> None:
    """Phase 2: delivered_at minus deliver_at. Observed envelope 6-251 ms."""
    registry.histogram(SCHEDULE_LATENESS_MS, partition=thread_partition).observe(lateness_ms)


def record_ws_connection(channel_kind: str = "turn-taking-thread") -> None:
    registry.counter(WS_CONNECTIONS_TOTAL, channel=channel_kind).inc()
    registry.gauge(WS_CONNECTIONS_ACTIVE, channel=channel_kind).inc()


def record_ws_close(code: int, channel_kind: str = "turn-taking-thread") -> None:
    """Code 4000 is the tested expired/garbage-grant close (spec/02)."""
    registry.counter(WS_CLOSES_TOTAL, channel=channel_kind, code=str(code)).inc()
    registry.gauge(WS_CONNECTIONS_ACTIVE, channel=channel_kind).dec()


def record_ws_frame(frame_type: str) -> None:
    """attached | turn_taking.typing | turn_taking.message."""
    registry.counter(WS_FRAMES_TOTAL, frame=frame_type).inc()


def record_epoch_advance() -> None:
    registry.counter(EPOCH_ADVANCES_TOTAL).inc()


def record_epoch_supersession() -> None:
    """Phase 3: stale respond returned {scheduled:[],superseded:true}, unbilled."""
    registry.counter(EPOCH_SUPERSESSIONS_TOTAL).inc()


def record_idempotency_replay(route: str, kind: str = "same_body") -> None:
    """Phase 4: owner-wide (owner,key) first-write-wins replay.

    ``kind`` distinguishes the three tested replay classes: ``same_body``,
    ``changed_body``, and ``other_scope`` (spec/02 §Idempotency).
    """
    registry.counter(IDEMPOTENCY_REPLAYS_TOTAL, route=route, kind=kind).inc()


def record_credit_reservation(component: str, credits: float) -> None:
    registry.counter(CREDIT_RESERVATIONS_TOTAL, component=component).inc()
    registry.counter("humalike_credits_reserved_total", component=component).inc(credits)


def record_credit_capture(component: str, credits: float) -> None:
    registry.counter(CREDIT_CAPTURES_TOTAL, component=component).inc()
    registry.counter(CREDITS_CAPTURED_TOTAL, component=component).inc(credits)


def record_credit_release(component: str, reason: str = "failure") -> None:
    """Reservation released without capture: failure, supersession, or reconcile."""
    registry.counter(CREDIT_RELEASES_TOTAL, component=component, reason=reason).inc()


def record_credit_denial(component: str) -> None:
    """402 documented default: insufficient credits before any billable work."""
    registry.counter(CREDIT_DENIALS_TOTAL, component=component).inc()


def record_job(kind: str, status: str, duration_ms: float | None = None) -> None:
    """kind: population | enhancement | evaluation | audit."""
    registry.counter(JOBS_TOTAL, kind=kind, status=status).inc()
    if duration_ms is not None:
        registry.histogram(JOB_DURATION_MS, kind=kind).observe(duration_ms)


def record_memory_recall(scope_hit: bool) -> None:
    registry.counter(MEMORY_RECALL_HITS_TOTAL,
                     result="hit" if scope_hit else "empty").inc()


def record_conformance_run(suite: str, passed: int, failed: int, skipped: int) -> None:
    """Release-gate signal: the live suites are the parity oracle (spec/08)."""
    registry.gauge(CONFORMANCE_ASSERTIONS, suite=suite, outcome="passed").set(passed)
    registry.gauge(CONFORMANCE_ASSERTIONS, suite=suite, outcome="failed").set(failed)
    registry.gauge(CONFORMANCE_ASSERTIONS, suite=suite, outcome="skipped").set(skipped)


@contextmanager
def timer(record, *args, **kwargs) -> Iterator[None]:
    """Time a block and hand the elapsed milliseconds to ``record``.

        with metrics.timer(metrics.record_model_stage, "turn_router"):
            verdict = router.decide(...)
    """
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        try:
            record(*args, elapsed_ms, **kwargs)
        except Exception:  # metrics never change a response
            pass


def snapshot() -> dict:
    """The JSON body served by GET /internal/metrics."""
    return registry.snapshot()


def prometheus_text() -> str:
    """Render the registry in Prometheus text exposition format.

    The Grafana dashboards are written against a Prometheus datasource that
    scrapes this rendering; the JSON snapshot is the same data for humans and
    for tests.
    """
    lines: list[str] = []

    def series(name: str, labels: dict, value) -> str:
        if labels:
            rendered = ",".join(
                f'{k}="{str(v)}"' for k, v in sorted(labels.items()))
            return f"{name}{{{rendered}}} {value}"
        return f"{name} {value}"

    data = registry.snapshot()
    for metric in data["counters"] + data["gauges"]:
        lines.append(series(metric["name"], metric["labels"], metric["value"]))
    for metric in data["histograms"]:
        for bucket in metric["buckets"]:
            labels = dict(metric["labels"], le=str(bucket["le"]))
            lines.append(series(metric["name"] + "_bucket", labels, bucket["count"]))
        lines.append(series(metric["name"] + "_sum", metric["labels"], metric["sum"]))
        lines.append(series(metric["name"] + "_count", metric["labels"], metric["count"]))
    return "\n".join(lines) + "\n"
