"""
Prometheus metrics definitions and FastAPI middleware for DeliverIQ.

Provides pre-defined metric objects for all services and a middleware
that auto-instruments request count and latency on every endpoint.
"""

import time
from collections.abc import Callable

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ── Shared registry ──────────────────────────────────────────────────────────
# Use the default registry so all metrics are on one /metrics endpoint.
# For testing, create an isolated registry with create_test_registry().

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

# ── Request-level metrics ────────────────────────────────────────────────────

REQUEST_COUNT = Counter(
    "deliveriq_http_requests_total",
    "Total HTTP requests",
    ["service", "method", "endpoint", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "deliveriq_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["service", "method", "endpoint"],
    buckets=LATENCY_BUCKETS,
)

# ── Saga metrics ─────────────────────────────────────────────────────────────

SAGA_DURATION = Histogram(
    "deliveriq_saga_duration_seconds",
    "Saga execution duration in seconds",
    ["outcome"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

SAGA_OUTCOME = Counter(
    "deliveriq_saga_outcomes_total",
    "Saga completion outcomes",
    ["outcome"],
)

# ── Outbox & DLQ ─────────────────────────────────────────────────────────────

OUTBOX_LAG = Gauge(
    "deliveriq_outbox_pending_events",
    "Number of pending outbox events",
    ["service"],
)

DLQ_DEPTH = Gauge(
    "deliveriq_dlq_depth",
    "Number of messages in dead letter queue",
    ["stream"],
)

# ── ETA / ML metrics ────────────────────────────────────────────────────────

ETA_DEGRADED_TOTAL = Counter(
    "deliveriq_eta_degraded_total",
    "Total predictions using degraded fallback",
)

ETA_PREDICTION_LATENCY = Histogram(
    "deliveriq_eta_prediction_latency_seconds",
    "ETA model inference latency",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
)

# ── Circuit breaker ──────────────────────────────────────────────────────────

BREAKER_STATE = Gauge(
    "deliveriq_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 0.5=half-open)",
    ["target_service"],
)

# ── ML monitoring metrics (Phase 6) ─────────────────────────────────────────

DRIFT_PSI = Gauge(
    "deliveriq_drift_psi",
    "Population Stability Index per feature",
    ["feature"],
)

ROLLING_MAE = Gauge(
    "deliveriq_rolling_mae",
    "Rolling Mean Absolute Error of ETA predictions",
)

LATE_RATE = Gauge(
    "deliveriq_late_rate",
    "Percentage of late deliveries (actual > predicted + 5min)",
)

INTERVAL_COVERAGE = Gauge(
    "deliveriq_interval_coverage",
    "Fraction of actuals within predicted [lower, upper] interval",
)

RETRAIN_GATE_EVALUATIONS = Counter(
    "deliveriq_retrain_gate_evaluations_total",
    "Total retrain gate evaluations",
    ["result"],  # triggered, suppressed
)


# ── FastAPI middleware ───────────────────────────────────────────────────────

class PrometheusMiddleware(BaseHTTPMiddleware):
    """Auto-instrument every request with count and latency metrics."""

    def __init__(self, app, service_name: str = "unknown"):
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip metrics endpoint itself to avoid recursion
        if request.url.path == "/metrics":
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        endpoint = request.url.path
        method = request.method
        status = str(response.status_code)

        REQUEST_COUNT.labels(
            service=self.service_name,
            method=method,
            endpoint=endpoint,
            status_code=status,
        ).inc()

        REQUEST_LATENCY.labels(
            service=self.service_name,
            method=method,
            endpoint=endpoint,
        ).observe(duration)

        return response


def add_metrics_middleware(app, service_name: str = "unknown"):
    """Add Prometheus metrics middleware to a FastAPI app."""
    app.add_middleware(PrometheusMiddleware, service_name=service_name)


def expose_metrics(app):
    """Add GET /metrics endpoint exposing Prometheus metrics."""
    from fastapi.responses import PlainTextResponse

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return PlainTextResponse(
            content=generate_latest().decode("utf-8"),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
