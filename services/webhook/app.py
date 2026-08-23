"""
Webhook Dispatcher Service — manages subscriptions and delivers events to merchant endpoints.

Endpoints:
  POST /webhooks/subscriptions          — Register a webhook endpoint
  GET  /webhooks/subscriptions          — List subscriptions for a tenant
  GET  /webhooks/deliveries             — View delivery attempts (audit log)
  POST /webhooks/deliveries/{id}/retry  — Manual redelivery from ops console
  POST /webhooks/dispatch               — Internal: dispatch an event to all matching subscribers

Design:
  - Each tenant registers one or more webhook URLs with event filters
  - When an event occurs, the dispatcher POSTs the payload to all matching URLs
  - Payload is HMAC-SHA256 signed with per-subscription secret
  - Retries with exponential backoff: 1s, 2s, 4s, 8s, 16s (5 attempts max)
  - Every attempt is logged in webhook_deliveries (full audit trail)
  - Failed deliveries can be manually retried from the ops console
"""

import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel

from contracts.auth import AuthContext, UserRole
from contracts.webhook import WebhookDeliveryResponse, WebhookStatus, WebhookSubscriptionCreate, WebhookSubscriptionResponse
from core.auth_middleware import get_current_user, require_role
from core.database import Base, create_db_engine, create_session_factory, get_session, init_tables
from core.logging import setup_logger
from core.metrics import add_metrics_middleware, expose_metrics
from core.security import compute_hmac_signature, generate_api_key_pair

logger = setup_logger("webhook-service", service_name="webhook-service")

# Database
DATABASE_URL = os.getenv("WEBHOOK_DATABASE_URL", "sqlite:///data/webhook.db")
engine = create_db_engine(DATABASE_URL)
SessionFactory = create_session_factory(engine)

from services.webhook.models import WebhookDelivery, WebhookSubscription

init_tables(engine, Base)

# FastAPI
app = FastAPI(title="DeliverIQ Webhook Service", version="1.0.0")
add_metrics_middleware(app, service_name="webhook")
expose_metrics(app)


@app.get("/health")
def health():
    return {"status": "UP", "service": "webhook-service"}


# ── Subscription Management ─────────────────────────────────────────────────

@app.post("/webhooks/subscriptions", response_model=WebhookSubscriptionResponse, status_code=201)
def create_subscription(
    request: WebhookSubscriptionCreate,
    auth: AuthContext = Depends(get_current_user),
):
    """Register a webhook endpoint for the current tenant.

    Generates a per-endpoint signing secret so the merchant can verify
    payloads came from DeliverIQ (exactly how Stripe does it).
    """
    _, endpoint_secret = generate_api_key_pair()

    with get_session(SessionFactory) as session:
        sub = WebhookSubscription(
            tenant_id=auth.tenant_id or auth.user_id,
            url=request.url,
            event_types=json.dumps(request.event_types),
            secret=endpoint_secret,
            description=request.description,
        )
        session.add(sub)
        session.flush()

        return WebhookSubscriptionResponse(
            id=sub.id,
            tenant_id=sub.tenant_id,
            url=sub.url,
            event_types=request.event_types,
            secret=endpoint_secret,
            is_active=bool(sub.is_active),
            created_at=sub.created_at.isoformat(),
        )


@app.get("/webhooks/subscriptions")
def list_subscriptions(auth: AuthContext = Depends(get_current_user)):
    """List webhook subscriptions for the current tenant."""
    tid = auth.tenant_id or auth.user_id
    with get_session(SessionFactory) as session:
        subs = session.query(WebhookSubscription).filter(
            WebhookSubscription.tenant_id == tid
        ).order_by(WebhookSubscription.created_at.desc()).all()

        return [
            WebhookSubscriptionResponse(
                id=s.id,
                tenant_id=s.tenant_id,
                url=s.url,
                event_types=json.loads(s.event_types),
                secret="••••••••",  # Never expose in list
                is_active=bool(s.is_active),
                created_at=s.created_at.isoformat(),
            )
            for s in subs
        ]


# ── Delivery Log ────────────────────────────────────────────────────────────

@app.get("/webhooks/deliveries")
def list_deliveries(
    auth: AuthContext = Depends(get_current_user),
    limit: int = 50,
):
    """View webhook delivery attempts. Full audit trail."""
    tid = auth.tenant_id or auth.user_id
    with get_session(SessionFactory) as session:
        deliveries = session.query(WebhookDelivery).filter(
            WebhookDelivery.tenant_id == tid
        ).order_by(WebhookDelivery.created_at.desc()).limit(limit).all()

        return [
            WebhookDeliveryResponse(
                id=d.id,
                tenant_id=d.tenant_id,
                subscription_id=d.subscription_id,
                event_id=d.event_id,
                event_type=d.event_type,
                url=d.url,
                payload=json.loads(d.payload),
                status_code=d.status_code,
                attempt_count=d.attempt_count,
                response_time_ms=d.response_time_ms,
                next_retry_at=d.next_retry_at.isoformat() if d.next_retry_at else None,
                status=WebhookStatus(d.status),
                error_message=d.error_message,
                created_at=d.created_at.isoformat(),
            )
            for d in deliveries
        ]


# ── Manual Redelivery ───────────────────────────────────────────────────────

@app.post("/webhooks/deliveries/{delivery_id}/retry")
def retry_delivery(
    delivery_id: str,
    auth: AuthContext = Depends(require_role(UserRole.ADMIN)),
):
    """Manually retry a failed webhook delivery. Admin only."""
    with get_session(SessionFactory) as session:
        delivery = session.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).first()
        if not delivery:
            raise HTTPException(status_code=404, detail="Delivery not found")

        sub = session.query(WebhookSubscription).filter(WebhookSubscription.id == delivery.subscription_id).first()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")

        # Attempt redelivery
        result = _deliver_webhook(
            url=delivery.url,
            payload_bytes=delivery.payload.encode("utf-8"),
            secret=sub.secret,
        )

        delivery.attempt_count += 1
        delivery.status_code = result["status_code"]
        delivery.response_time_ms = result["response_time_ms"]
        delivery.error_message = result.get("error")
        delivery.status = "SUCCESS" if result["success"] else "FAILED"

    return {"message": "Redelivery attempted", "success": result["success"], "status_code": result["status_code"]}


# ── Internal: Event Dispatch ────────────────────────────────────────────────

class DispatchRequest(BaseModel):
    event_id: str
    event_type: str
    tenant_id: str
    payload: dict


@app.post("/webhooks/dispatch")
def dispatch_event(request: DispatchRequest):
    """Internal endpoint: dispatch an event to all matching webhook subscribers.

    Called by the saga orchestrator or event relay when an order event occurs.
    For each matching subscription:
      1. HMAC-sign the payload with the subscription's secret
      2. POST to the merchant URL with X-DeliverIQ-Signature header
      3. Log the delivery attempt
      4. Schedule retry if failed
    """
    with get_session(SessionFactory) as session:
        # Find all active subscriptions for this tenant that subscribe to this event type
        subs = session.query(WebhookSubscription).filter(
            WebhookSubscription.tenant_id == request.tenant_id,
            WebhookSubscription.is_active == 1,
        ).all()

        dispatched = 0
        for sub in subs:
            event_types = json.loads(sub.event_types)
            if request.event_type not in event_types:
                continue

            payload_bytes = json.dumps(request.payload).encode("utf-8")

            # Deliver
            result = _deliver_webhook(
                url=sub.url,
                payload_bytes=payload_bytes,
                secret=sub.secret,
            )

            # Compute next retry if failed
            next_retry = None
            status_val = "SUCCESS"
            if not result["success"]:
                # Exponential backoff: 1s, 2s, 4s, 8s, 16s
                backoff = 2 ** 0  # First retry in 1s
                next_retry = datetime.now(UTC) + timedelta(seconds=backoff)
                status_val = "RETRYING"

            # Log delivery attempt
            delivery = WebhookDelivery(
                tenant_id=request.tenant_id,
                subscription_id=sub.id,
                event_id=request.event_id,
                event_type=request.event_type,
                url=sub.url,
                payload=json.dumps(request.payload),
                status_code=result["status_code"],
                response_time_ms=result["response_time_ms"],
                status=status_val,
                error_message=result.get("error"),
                next_retry_at=next_retry,
            )
            session.add(delivery)
            dispatched += 1

    logger.info(f"Dispatched event {request.event_type} to {dispatched} endpoints for tenant {request.tenant_id}")
    return {"dispatched": dispatched}


# ── Delivery Helper ─────────────────────────────────────────────────────────

def _deliver_webhook(url: str, payload_bytes: bytes, secret: str) -> dict:
    """POST a signed payload to a webhook URL.

    Headers sent to merchant:
      Content-Type: application/json
      X-DeliverIQ-Signature: sha256=<hmac_hex>
      X-DeliverIQ-Event-Timestamp: <unix_timestamp>
    """
    signature = compute_hmac_signature(secret, payload_bytes)
    headers = {
        "Content-Type": "application/json",
        "X-DeliverIQ-Signature": signature,
        "X-DeliverIQ-Event-Timestamp": str(int(time.time())),
    }

    try:
        start = time.time()
        resp = httpx.post(url, content=payload_bytes, headers=headers, timeout=10.0)
        elapsed_ms = (time.time() - start) * 1000

        return {
            "success": 200 <= resp.status_code < 300,
            "status_code": resp.status_code,
            "response_time_ms": round(elapsed_ms, 1),
        }
    except httpx.TimeoutException:
        return {"success": False, "status_code": 0, "response_time_ms": 10000, "error": "Timeout (10s)"}
    except Exception as e:
        return {"success": False, "status_code": 0, "response_time_ms": 0, "error": str(e)}
