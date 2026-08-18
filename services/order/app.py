"""
Order Service — FastAPI application.

Endpoints:
  POST /orders          — Create an order (requires Idempotency-Key header)
  GET  /orders/{id}     — Retrieve order by ID
  PATCH /orders/{id}    — Update order status (used by saga orchestrator)
"""

import json
import os
import uuid

from fastapi import FastAPI, Header, HTTPException, status

from contracts.events import EventEnvelope, EventType
from contracts.order import CreateOrderRequest, OrderResponse, OrderStatus
from core.database import Base, create_db_engine, create_session_factory, get_session, init_tables
from core.idempotency import IdempotencyStore
from core.logging import setup_logger
from core.metrics import add_metrics_middleware, expose_metrics
from core.outbox import write_outbox_event

logger = setup_logger("order-service", service_name="order-service")

# Database setup
DATABASE_URL = os.getenv("ORDERS_DATABASE_URL", "sqlite:///data/orders.db")
engine = create_db_engine(DATABASE_URL)
SessionFactory = create_session_factory(engine)

# Import models so Base.metadata knows about them
from services.order.models import Order

# Create tables
init_tables(engine, Base)

# Idempotency store
idem_store = IdempotencyStore()

# FastAPI app
app = FastAPI(title="DeliverIQ Order Service", version="1.0.0")
add_metrics_middleware(app, service_name="order")
expose_metrics(app)


@app.get("/health")
def health():
    return {"status": "UP", "service": "order-service"}


@app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_202_ACCEPTED)
def create_order(
    request: CreateOrderRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    """Create a new order with atomic outbox event write."""

    # Check idempotency
    cached = idem_store.get(idempotency_key)
    if cached:
        return OrderResponse(**cached["response"])

    order_id = f"ORD-{uuid.uuid4().hex[:12].upper()}"

    with get_session(SessionFactory) as session:
        # Write order row
        order = Order(
            order_id=order_id,
            customer_id=request.customer_id,
            restaurant_id=request.restaurant_id,
            items=json.dumps(request.items),
            total_amount=request.total_amount,
            status=OrderStatus.CREATED.value,
            idempotency_key=idempotency_key,
        )
        session.add(order)

        # Write outbox event in the SAME transaction
        event = EventEnvelope(
            event_type=EventType.ORDER_CREATED,
            correlation_id=order_id,
            idempotency_key=idempotency_key,
            payload={
                "order_id": order_id,
                "customer_id": request.customer_id,
                "restaurant_id": request.restaurant_id,
                "items": request.items,
                "total_amount": request.total_amount,
            },
        )
        write_outbox_event(
            session=session,
            event_type=EventType.ORDER_CREATED.value,
            stream_name="order.created",
            payload=event.to_stream_dict(),
            event_id=event.event_id,
        )
        # session.commit() happens automatically via get_session context manager

    response = OrderResponse(
        order_id=order_id,
        status=OrderStatus.CREATED,
        total_amount=request.total_amount,
    )

    # Cache for idempotent replays
    idem_store.set(idempotency_key, response.model_dump(), status_code=202)

    logger.info(f"Order {order_id} created for customer {request.customer_id}")
    return response


@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str):
    """Retrieve an order by its ID."""
    with get_session(SessionFactory) as session:
        order = session.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

        return OrderResponse(
            order_id=order.order_id,
            status=OrderStatus(order.status),
            total_amount=order.total_amount,
            eta_minutes=order.eta_minutes,
            eta_lower=order.eta_lower,
            eta_upper=order.eta_upper,
            degraded=bool(order.degraded),
        )


@app.patch("/orders/{order_id}")
def update_order_status(
    order_id: str,
    new_status: str,
    eta_minutes: float | None = None,
    eta_lower: float | None = None,
    eta_upper: float | None = None,
    degraded: bool = False,
):
    """Update order status — called by the saga orchestrator."""
    with get_session(SessionFactory) as session:
        order = session.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

        order.status = new_status
        if eta_minutes is not None:
            order.eta_minutes = eta_minutes
            order.eta_lower = eta_lower
            order.eta_upper = eta_upper
            order.degraded = 1 if degraded else 0

    return {"order_id": order_id, "status": new_status}
