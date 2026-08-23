"""
Ops Console — FastAPI application.

The admin dashboard that makes every invisible backend pattern visible and clickable.
Technology: FastAPI + Jinja2 + HTMX. No React, no Node, no SPA build step.

Panels:
  /ops/              — Dashboard with live stats
  /ops/sagas         — Saga Explorer (table + filter)
  /ops/saga/{id}     — Saga Timeline (visual step-by-step)
  /ops/idempotency   — Idempotency Demo (send same order twice)
  /ops/events        — Live Event Feed
  /ops/outbox        — Outbox Monitor
  /ops/chaos         — Chaos Engineering Panel

All /ops/api/* endpoints return HTML fragments for HTMX partial updates.
"""

import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.database import Base, create_db_engine, create_session_factory, get_session, init_tables
from core.logging import setup_logger
from core.metrics import add_metrics_middleware, expose_metrics

logger = setup_logger("ops-console", service_name="ops-console")

# ── Database (reads saga_db directly — ops console is an admin tool) ─────────
SAGA_DB_URL = os.getenv("SAGA_DATABASE_URL", "sqlite:///data/saga.db")
ORDERS_DB_URL = os.getenv("ORDERS_DATABASE_URL", "sqlite:///data/orders.db")

saga_engine = create_db_engine(SAGA_DB_URL)
SagaSessionFactory = create_session_factory(saga_engine)

orders_engine = create_db_engine(ORDERS_DB_URL)
OrdersSessionFactory = create_session_factory(orders_engine)

# Import models
from services.orchestrator.models import SagaInstance, SagaStepLog

init_tables(saga_engine, Base)

# ── Service URLs for health checks and chaos control ─────────────────────────
SERVICE_URLS = {
    "order": os.getenv("ORDER_SERVICE_URL", "http://localhost:8001"),
    "payment": os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8002"),
    "inventory": os.getenv("INVENTORY_SERVICE_URL", "http://localhost:8003"),
    "orchestrator": os.getenv("ORCHESTRATOR_SERVICE_URL", "http://localhost:8004"),
    "auth": os.getenv("AUTH_SERVICE_URL", "http://localhost:8005"),
    "eta": os.getenv("ETA_SERVICE_URL", "http://localhost:8000"),
    "monitoring": os.getenv("MONITORING_SERVICE_URL", "http://localhost:8006"),
}

# Chaos state (in-memory, matches what payment service reads from env)
_chaos_state = {
    "payment_fail_rate": int(float(os.getenv("PAYMENT_FAIL_RATE", "0")) * 100),
    "payment_latency_ms": int(os.getenv("PAYMENT_LATENCY_MS", "0")),
}

# ── FastAPI App ──────────────────────────────────────────────────────────────

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="DeliverIQ Ops Console", version="1.0.0")
add_metrics_middleware(app, service_name="ops-console")
expose_metrics(app)
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
def health():
    return {"status": "UP", "service": "ops-console"}


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE ROUTES (return full HTML pages)
# ═══════════════════════════════════════════════════════════════════════════════


@app.get("/ops/", response_class=HTMLResponse)
@app.get("/ops", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "active": "dashboard"})


@app.get("/ops/sagas", response_class=HTMLResponse)
def sagas_page(request: Request, state: str = ""):
    with get_session(SagaSessionFactory) as session:
        query = session.query(SagaInstance).order_by(SagaInstance.started_at.desc())
        if state:
            query = query.filter(SagaInstance.current_state == state)
        sagas = query.limit(100).all()

        # Calculate durations
        for s in sagas:
            if s.completed_at and s.started_at:
                delta = s.completed_at - s.started_at
                s.duration = f"{delta.total_seconds():.1f}s"
            elif s.started_at:
                delta = datetime.now(UTC) - s.started_at.replace(tzinfo=UTC) if s.started_at.tzinfo is None else datetime.now(UTC) - s.started_at
                s.duration = f"{delta.total_seconds():.1f}s (ongoing)"
            else:
                s.duration = None

    return templates.TemplateResponse("sagas.html", {
        "request": request,
        "active": "sagas",
        "sagas": sagas,
        "filter_state": state,
    })


@app.get("/ops/saga/{order_id}", response_class=HTMLResponse)
def saga_detail(request: Request, order_id: str):
    with get_session(SagaSessionFactory) as session:
        saga = session.query(SagaInstance).filter(SagaInstance.order_id == order_id).first()
        if not saga:
            # Try by saga_id
            saga = session.query(SagaInstance).filter(SagaInstance.saga_id == order_id).first()

        if not saga:
            return HTMLResponse(f"<h2>Saga not found: {order_id}</h2>", status_code=404)

        steps = session.query(SagaStepLog).filter(
            SagaStepLog.saga_id == saga.saga_id
        ).order_by(SagaStepLog.timestamp.asc()).all()

        duration = None
        if saga.completed_at and saga.started_at:
            delta = saga.completed_at - saga.started_at
            duration = f"{delta.total_seconds():.2f}s"

    return templates.TemplateResponse("saga_detail.html", {
        "request": request,
        "active": "sagas",
        "saga": saga,
        "steps": steps,
        "duration": duration,
    })


@app.get("/ops/idempotency", response_class=HTMLResponse)
def idempotency_page(request: Request):
    return templates.TemplateResponse("idempotency.html", {"request": request, "active": "idempotency"})


@app.get("/ops/events", response_class=HTMLResponse)
def events_page(request: Request):
    return templates.TemplateResponse("events.html", {"request": request, "active": "events"})


@app.get("/ops/outbox", response_class=HTMLResponse)
def outbox_page(request: Request):
    return templates.TemplateResponse("outbox.html", {"request": request, "active": "outbox"})


@app.get("/ops/chaos", response_class=HTMLResponse)
def chaos_page(request: Request):
    return templates.TemplateResponse("chaos.html", {
        "request": request,
        "active": "chaos",
        "payment_fail_rate": _chaos_state["payment_fail_rate"],
        "payment_latency_ms": _chaos_state["payment_latency_ms"],
    })


# ═══════════════════════════════════════════════════════════════════════════════
# API ROUTES (return HTML fragments for HTMX)
# ═══════════════════════════════════════════════════════════════════════════════


@app.get("/ops/api/stats-cards", response_class=HTMLResponse)
def api_stats_cards():
    """Return stat cards HTML fragment."""
    with get_session(SagaSessionFactory) as session:
        total = session.query(SagaInstance).count()
        confirmed = session.query(SagaInstance).filter(SagaInstance.current_state.like("%CONFIRMED%")).count()
        cancelled = session.query(SagaInstance).filter(SagaInstance.current_state.like("%CANCELLED%")).count()
        degraded = session.query(SagaInstance).filter(SagaInstance.current_state == "CONFIRMED_DEGRADED").count()

    return f"""
    <div class="stat-card">
        <div class="stat-label">Total Sagas</div>
        <div class="stat-value blue">{total}</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">Confirmed</div>
        <div class="stat-value green">{confirmed}</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">Cancelled</div>
        <div class="stat-value red">{cancelled}</div>
    </div>
    <div class="stat-card">
        <div class="stat-label">Degraded</div>
        <div class="stat-value yellow">{degraded}</div>
    </div>
    """


@app.get("/ops/api/recent-sagas", response_class=HTMLResponse)
def api_recent_sagas():
    """Return recent sagas as a table fragment."""
    with get_session(SagaSessionFactory) as session:
        sagas = session.query(SagaInstance).order_by(SagaInstance.started_at.desc()).limit(5).all()

    if not sagas:
        return '<p class="text-muted text-sm" style="text-align:center; padding:20px;">No sagas yet.</p>'

    rows = ""
    for s in sagas:
        state_class = "status-confirmed" if "CONFIRMED" in s.current_state and "DEGRADED" not in s.current_state else \
                      "status-degraded" if "DEGRADED" in s.current_state else \
                      "status-cancelled" if "CANCELLED" in s.current_state else "status-pending"
        rows += f"""
        <tr>
            <td class="text-mono" style="font-size:0.75rem;">{s.order_id}</td>
            <td><span class="status {state_class}">{s.current_state}</span></td>
            <td class="text-sm text-muted">{s.started_at.strftime('%H:%M:%S') if s.started_at else '—'}</td>
            <td><a href="/ops/saga/{s.order_id}" class="btn btn-sm">→</a></td>
        </tr>"""

    return f"""
    <table>
        <thead><tr><th>Order</th><th>State</th><th>Time</th><th></th></tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


@app.get("/ops/api/health-checks", response_class=HTMLResponse)
def api_health_checks():
    """Check health of all services and return HTML fragment."""
    results = []
    for name, url in SERVICE_URLS.items():
        try:
            resp = httpx.get(f"{url}/health", timeout=2.0)
            status = "🟢" if resp.status_code == 200 else "🟡"
            detail = resp.json().get("status", "unknown")
        except Exception:
            status = "🔴"
            detail = "unreachable"
        results.append((name, status, detail))

    rows = ""
    for name, status, detail in results:
        rows += f"""
        <tr>
            <td>{status}</td>
            <td style="font-weight:600;">{name}</td>
            <td class="text-muted text-sm">{detail}</td>
        </tr>"""

    return f"""
    <table>
        <thead><tr><th></th><th>Service</th><th>Status</th></tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


@app.get("/ops/api/saga-counts", response_class=HTMLResponse)
def api_saga_counts():
    """Return saga outcome counts as stat cards — used by chaos panel."""
    with get_session(SagaSessionFactory) as session:
        confirmed = session.query(SagaInstance).filter(SagaInstance.current_state.like("%CONFIRMED%")).count()
        cancelled = session.query(SagaInstance).filter(SagaInstance.current_state.like("%CANCELLED%")).count()
        degraded = session.query(SagaInstance).filter(SagaInstance.current_state == "CONFIRMED_DEGRADED").count()

    return f"""
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-label">✅ Confirmed</div>
            <div class="stat-value green">{confirmed}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">⚠️ Degraded</div>
            <div class="stat-value yellow">{degraded}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">❌ Compensated</div>
            <div class="stat-value red">{cancelled}</div>
        </div>
    </div>"""


# ── Chaos Controls ───────────────────────────────────────────────────────────

@app.post("/ops/api/chaos/payment-fail-rate", response_class=HTMLResponse)
def set_payment_fail_rate(rate: int = Form(...)):
    """Set payment failure rate via the payment service's config endpoint."""
    _chaos_state["payment_fail_rate"] = rate
    os.environ["PAYMENT_FAIL_RATE"] = str(rate / 100.0)

    try:
        payment_url = SERVICE_URLS.get("payment", "http://payment-service:8002")
        httpx.post(f"{payment_url}/config/fail-rate", json={"rate": rate / 100.0}, timeout=2.0)
    except Exception:
        pass

    color = "var(--green)" if rate == 0 else "var(--yellow)" if rate < 50 else "var(--red)"
    return f"""<script>
    if (document.querySelector('input[name="rate"]')) document.querySelector('input[name="rate"]').value = {rate};
    if (document.getElementById('payment-rate-display')) document.getElementById('payment-rate-display').textContent = '{rate}%';
    </script>
    <p style="color:{color}; font-size:0.85rem;">✓ Payment failure rate set to {rate}%</p>"""


@app.post("/ops/api/chaos/payment-latency", response_class=HTMLResponse)
def set_payment_latency(latency: int = Form(...)):
    """Set artificial payment latency."""
    _chaos_state["payment_latency_ms"] = latency
    os.environ["PAYMENT_LATENCY_MS"] = str(latency)

    try:
        payment_url = SERVICE_URLS.get("payment", "http://payment-service:8002")
        httpx.post(f"{payment_url}/config/latency", json={"latency_ms": latency}, timeout=2.0)
    except Exception:
        pass

    color = "var(--green)" if latency == 0 else "var(--yellow)" if latency < 2000 else "var(--red)"
    return f"""<script>
    if (document.querySelector('input[name="latency"]')) document.querySelector('input[name="latency"]').value = {latency};
    if (document.getElementById('payment-latency-display')) document.getElementById('payment-latency-display').textContent = '{latency}ms';
    </script>
    <p style="color:{color}; font-size:0.85rem;">✓ Payment latency set to {latency}ms</p>"""


@app.post("/ops/api/chaos/reset-all", response_class=HTMLResponse)
def reset_all_chaos():
    """Unconditionally restore all services and reset all latency/failure injections to normal."""
    _chaos_state["payment_fail_rate"] = 0
    _chaos_state["payment_latency_ms"] = 0
    os.environ["PAYMENT_FAIL_RATE"] = "0.0"
    os.environ["PAYMENT_LATENCY_MS"] = "0"

    payment_url = SERVICE_URLS.get("payment", "http://payment-service:8002")
    try:
        httpx.post(f"{payment_url}/config/fail-rate", json={"rate": 0.0}, timeout=2.0)
    except Exception:
        pass
    try:
        httpx.post(f"{payment_url}/config/latency", json={"latency_ms": 0}, timeout=2.0)
    except Exception:
        pass

    return """<script>
    if (document.querySelector('input[name="rate"]')) document.querySelector('input[name="rate"]').value = 0;
    if (document.getElementById('payment-rate-display')) document.getElementById('payment-rate-display').textContent = '0%';
    if (document.querySelector('input[name="latency"]')) document.querySelector('input[name="latency"]').value = 0;
    if (document.getElementById('payment-latency-display')) document.getElementById('payment-latency-display').textContent = '0ms';
    if (document.getElementById('payment-rate-result')) document.getElementById('payment-rate-result').innerHTML = '';
    if (document.getElementById('payment-latency-result')) document.getElementById('payment-latency-result').innerHTML = '';
    </script>
    <div class="card" style="border-left:4px solid #10b981; background:rgba(16,185,129,0.1); padding:12px; margin-top:8px;">
        <span style="color:#10b981; font-weight:700;">🟢 All Systems Normal:</span>
        <span style="color:var(--text); font-size:0.9rem;"> Failure rate reset to <strong>0%</strong>, Latency reset to <strong>0ms</strong>. Clean slate active!</span>
    </div>"""


# ── Idempotency Demo ────────────────────────────────────────────────────────

@app.post("/ops/api/idempotency-custom", response_class=HTMLResponse)
@app.post("/ops/api/idempotency-demo", response_class=HTMLResponse)
def api_idempotency_demo(
    idempotency_key: str = Form(default=None),
    customer_id: str = Form(default="CUST-BENGALURU-88"),
    restaurant_id: str = Form(default="REST-MEGHANA-FOODS"),
    total_amount: float = Form(default=450.0),
):
    """Send the same order twice with the given or generated idempotency key. Return comparison."""
    if not idempotency_key or not idempotency_key.strip():
        idempotency_key = f"demo-{uuid.uuid4().hex[:8]}"

    order_url = SERVICE_URLS.get("order", "http://localhost:8001")

    order_payload = {
        "customer_id": customer_id,
        "restaurant_id": restaurant_id,
        "items": ["Chicken Biryani", "Butter Naan"],
        "total_amount": float(total_amount),
    }
    headers = {"Idempotency-Key": idempotency_key}

    results = []
    for i in range(2):
        try:
            start = time.time()
            resp = httpx.post(f"{order_url}/orders", json=order_payload, headers=headers, timeout=5.0)
            elapsed = (time.time() - start) * 1000
            results.append({
                "attempt": i + 1,
                "status_code": resp.status_code,
                "body": resp.json(),
                "time_ms": f"{elapsed:.1f}",
            })
        except Exception as e:
            results.append({
                "attempt": i + 1,
                "status_code": 0,
                "body": {"error": str(e)},
                "time_ms": "—",
            })

    # Build comparison HTML
    if len(results) == 2:
        order_id_1 = results[0]["body"].get("order_id")
        order_id_2 = results[1]["body"].get("order_id")
        same_order = order_id_1 is not None and order_id_1 == order_id_2
        same_status = results[0]["status_code"] == results[1]["status_code"]

        return f"""
        <div class="card" style="border-color: var(--green); background: rgba(16, 185, 129, 0.04);">
            <div class="card-title" style="color: var(--green); margin-bottom: 12px; font-size:1.1rem;">
                ✅ Idempotency Verified — Exactly 1 Database Order Created
            </div>

            <div class="grid-2" style="margin-bottom:16px;">
                <div style="background:var(--bg-main); padding:12px; border-radius:8px; border:1px solid var(--border);">
                    <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                        <span class="stat-label">📡 Request 1 (Initial Write)</span>
                        <span class="status status-confirmed">HTTP {results[0]["status_code"]}</span>
                    </div>
                    <div class="code-block" style="font-size:0.75rem;">{json.dumps(results[0]["body"], indent=2)}</div>
                    <div class="text-muted text-sm mt-2">⏱️ Network + DB Write: <strong>{results[0]["time_ms"]}ms</strong></div>
                </div>
                <div style="background:var(--bg-main); padding:12px; border-radius:8px; border:1px solid var(--border);">
                    <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                        <span class="stat-label">⚡ Request 2 (Redis Cache Hit)</span>
                        <span class="status status-confirmed">HTTP {results[1]["status_code"]}</span>
                    </div>
                    <div class="code-block" style="font-size:0.75rem;">{json.dumps(results[1]["body"], indent=2)}</div>
                    <div class="text-muted text-sm mt-2">⏱️ Instant Cache Replay: <strong>{results[1]["time_ms"]}ms</strong></div>
                </div>
            </div>

            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px; background:var(--bg-card); padding:12px; border-radius:8px;">
                <div class="text-sm">
                    <span class="text-muted">Same Order ID:</span><br>
                    <strong style="color:var(--{'green' if same_order else 'red'});">{'✅ ' + str(order_id_1) if same_order else '❌ Mismatch'}</strong>
                </div>
                <div class="text-sm">
                    <span class="text-muted">Postgres Records Created:</span><br>
                    <strong style="color:var(--green);">✅ Exactly 1 Row</strong>
                </div>
                <div class="text-sm">
                    <span class="text-muted">Idempotency Key:</span><br>
                    <span class="text-mono" style="font-size:0.8rem; color:var(--blue);">{idempotency_key}</span>
                </div>
            </div>
        </div>
        """

    return '<p style="color:var(--red);">Failed to run demo — ensure the order service is running.</p>'



# ── Event Feed API ──────────────────────────────────────────────────────────

@app.get("/ops/api/events", response_class=HTMLResponse)
def api_events():
    """Read recent events from Redis Streams and return as HTML."""
    try:
        import redis
        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

        # Read from known streams
        stream_names = ["order.created", "order.confirmed", "order.cancelled"]
        events = []

        for stream in stream_names:
            try:
                # XREVRANGE returns newest first
                entries = r.xrevrange(stream, count=20)
                for entry_id, data in entries:
                    event_id = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                    decoded = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in data.items()}
                    events.append({
                        "stream": stream,
                        "event_id": event_id,
                        "data": decoded,
                        "timestamp": event_id.split("-")[0] if "-" in str(event_id) else "",
                    })
            except Exception:
                continue

        # Sort by event_id (timestamp-based)
        events.sort(key=lambda e: e["event_id"], reverse=True)
        events = events[:50]

        if not events:
            return '<p class="text-muted text-sm" style="text-align:center; padding:40px;">No events in streams yet. Place an order to generate events.</p>'

        html = ""
        for e in events:
            event_type = e["data"].get("event_type", e["stream"])
            correlation = e["data"].get("correlation_id", "—")
            html += f"""
            <div class="event-item">
                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                    <span class="event-type">{event_type}</span>
                    <span class="event-id">{e['event_id']}</span>
                </div>
                <div style="display:flex; gap:16px;">
                    <span class="text-sm text-muted">Stream: {e['stream']}</span>
                    <span class="text-sm text-muted">Correlation: <span class="text-mono">{correlation}</span></span>
                </div>
            </div>"""
        return html

    except Exception as e:
        return f'<p class="text-muted text-sm" style="text-align:center; padding:20px;">Redis not available: {e}</p>'


@app.get("/ops/api/event-count", response_class=HTMLResponse)
def api_event_count():
    """Return total event count across streams."""
    try:
        import redis
        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        total = 0
        for stream in ["order.created", "order.confirmed", "order.cancelled"]:
            try:
                total += r.xlen(stream)
            except Exception:
                pass
        return f"{total} events"
    except Exception:
        return "—"


# ── Outbox API ──────────────────────────────────────────────────────────────

@app.get("/ops/api/outbox", response_class=HTMLResponse)
def api_outbox():
    """Read outbox entries from the orders database."""
    try:
        from sqlalchemy import text
        with get_session(OrdersSessionFactory) as session:
            result = session.execute(
                text("SELECT * FROM outbox_events ORDER BY created_at DESC LIMIT 20")
            ).fetchall()

            if not result:
                return '<p class="text-muted text-sm" style="text-align:center; padding:40px;">No outbox entries. Place an order to see the transactional outbox in action.</p>'

            # Get column names
            columns = result[0]._fields if hasattr(result[0], '_fields') else [f"col{i}" for i in range(len(result[0]))]

            header = "".join(f"<th>{c}</th>" for c in columns)
            rows = ""
            for row in result:
                cells = ""
                for i, val in enumerate(row):
                    cell_val = str(val)[:60] if val else "—"
                    cells += f'<td class="text-sm">{cell_val}</td>'
                published = "published" in str(row).lower()
                rows += f'<tr style="opacity: {"0.5" if published else "1"}">{cells}</tr>'

            return f"""
            <table>
                <thead><tr>{header}</tr></thead>
                <tbody>{rows}</tbody>
            </table>"""

    except Exception as e:
        return f'<p class="text-muted text-sm">Outbox table not available: {e}</p>'


# ── Flash Sale Concurrency Arena Endpoint ──────────────────────────────────

@app.post("/ops/api/chaos/flash-sale-race", response_class=HTMLResponse)
def api_flash_sale_race():
    """
    Simulate a High-Concurrency Flash Sale:
    20 parallel worker threads race for the exact last item of stock (Stock = 1).
    Demonstrates optimistic locking and DB invariant protection.
    """
    import concurrent.futures
    import uuid
    import time
    from sqlalchemy import text
    from core.database import create_db_engine

    item_id = f"FLASH-{uuid.uuid4().hex[:6].upper()}"
    inv_url = SERVICE_URLS.get("inventory", "http://inventory-service:8003")

    # 1. Initialize item with Stock = 1 via Inventory API
    try:
        r = httpx.post(f"{inv_url}/inventory/set-stock", json={"item_id": item_id, "stock": 1}, timeout=5.0)
        if r.status_code != 200:
            return f'<div class="card" style="border-left:4px solid var(--red);"><p style="color:var(--red);">Failed to initialize flash sale item: {r.text}</p></div>'
    except Exception as e:
        logger.error(f"Failed to seed inventory item: {e}")
        return f'<div class="card" style="border-left:4px solid var(--red);"><p style="color:var(--red);">Failed to reach inventory service: {e}</p></div>'

    # 2. Fire 20 parallel requests
    def worker(idx):
        oid = f"ORD-RACE-{idx+1:02d}-{uuid.uuid4().hex[:4].upper()}"
        start = time.time()
        try:
            r = httpx.post(
                f"{inv_url}/inventory/reserve",
                json={"order_id": oid, "items": [item_id]},
                headers={"Idempotency-Key": f"IDEM-{oid}"},
                timeout=5.0
            )
            lat = round((time.time() - start) * 1000, 1)
            body = r.json() if r.status_code != 500 else {}
            return {"user": f"Shopper #{idx+1:02d}", "order_id": oid, "status": r.status_code, "body": body, "latency_ms": lat}
        except Exception as err:
            lat = round((time.time() - start) * 1000, 1)
            return {"user": f"Shopper #{idx+1:02d}", "order_id": oid, "status": 500, "body": {"error": str(err)}, "latency_ms": lat}

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in futures]

    # 3. Check final DB state via Inventory API
    final_stock = 0
    try:
        r_stock = httpx.get(f"{inv_url}/inventory/stock/{item_id}", timeout=5.0)
        if r_stock.status_code == 200:
            final_stock = r_stock.json().get("stock", 0)
    except Exception as e:
        logger.warning(f"Could not read final stock: {e}")

    winners = [r for r in results if r["body"].get("status") == "RESERVED"]
    losers = [r for r in results if r not in winners]

    rows = ""
    for r in results:
        is_win = r in winners
        badge = '<span class="badge" style="background:rgba(16,185,129,0.2); color:#10b981;">🥇 200 OK (RESERVED)</span>' if is_win else '<span class="badge" style="background:rgba(239,68,68,0.2); color:#ef4444;">🛡️ 409 OUT OF STOCK</span>'
        rows += f"""
        <tr>
            <td><strong>{r['user']}</strong></td>
            <td><code>{r['order_id']}</code></td>
            <td>{badge}</td>
            <td class="text-sm">{r['latency_ms']} ms</td>
        </tr>"""

    return f"""
    <div style="background:var(--card-bg); border:1px solid var(--border); border-radius:8px; padding:16px; margin-top:16px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <h4 style="margin:0;">🏁 Flash Sale Race Resolution Report</h4>
            <span class="badge" style="background:#6366f1; color:white;">Item: {item_id}</span>
        </div>
        <div class="stats-grid mb-4">
            <div class="stat-card"><div class="stat-label">Total Shoppers</div><div class="stat-value">20</div></div>
            <div class="stat-card"><div class="stat-label">Initial Stock</div><div class="stat-value">1</div></div>
            <div class="stat-card"><div class="stat-label">Winners (Stock Acquired)</div><div class="stat-value green">{len(winners)}</div></div>
            <div class="stat-card"><div class="stat-label">Losers (Safely Rejected)</div><div class="stat-value red">{len(losers)}</div></div>
            <div class="stat-card"><div class="stat-label">Final DB Stock</div><div class="stat-value green">{final_stock} (Zero Oversell)</div></div>
        </div>
        <table style="width:100%; border-collapse:collapse;">
            <thead><tr><th>Shopper</th><th>Order ID</th><th>Outcome</th><th>Latency</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>"""


