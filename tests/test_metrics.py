"""
Tests for Prometheus metrics instrumentation — Phase 5.

Covers:
- Metric counter increments via middleware
- Prometheus /metrics endpoint returns valid text format
- Metric labels are correctly applied
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.metrics import (
    add_metrics_middleware,
    expose_metrics,
)


def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app with metrics instrumentation for testing."""
    app = FastAPI()

    @app.get("/test-endpoint")
    def test_endpoint():
        return {"status": "ok"}

    @app.get("/test-error")
    def test_error():
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=500, content={"error": "boom"})

    add_metrics_middleware(app, service_name="test-service")
    expose_metrics(app)
    return app


def test_metrics_endpoint_returns_prometheus_format():
    """The /metrics endpoint should return valid Prometheus text exposition."""
    app = _create_test_app()
    client = TestClient(app)

    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    # Should contain at least the default process metrics or our custom ones
    body = response.text
    assert "deliveriq" in body or "python" in body or "process" in body


def test_request_increments_counter():
    """Making a request should increment the request counter."""
    app = _create_test_app()
    client = TestClient(app)

    # Make a test request
    response = client.get("/test-endpoint")
    assert response.status_code == 200

    # Check metrics endpoint for the counter
    metrics_response = client.get("/metrics")
    body = metrics_response.text
    assert "deliveriq_http_requests_total" in body


def test_request_records_latency():
    """Making a request should record latency in the histogram."""
    app = _create_test_app()
    client = TestClient(app)

    client.get("/test-endpoint")

    metrics_response = client.get("/metrics")
    body = metrics_response.text
    assert "deliveriq_http_request_duration_seconds" in body


def test_metrics_labels():
    """Metrics should include service, method, endpoint, and status_code labels."""
    app = _create_test_app()
    client = TestClient(app)

    client.get("/test-endpoint")

    metrics_response = client.get("/metrics")
    body = metrics_response.text
    # Check that the service label is included
    assert 'service="test-service"' in body
    assert 'method="GET"' in body
    assert 'endpoint="/test-endpoint"' in body


def test_metrics_endpoint_not_instrumented():
    """The /metrics endpoint itself should NOT be instrumented (no recursion)."""
    app = _create_test_app()
    client = TestClient(app)

    # Hit only the metrics endpoint
    client.get("/metrics")
    client.get("/metrics")

    metrics_response = client.get("/metrics")
    body = metrics_response.text
    # Should NOT have /metrics as an instrumented endpoint
    assert 'endpoint="/metrics"' not in body
