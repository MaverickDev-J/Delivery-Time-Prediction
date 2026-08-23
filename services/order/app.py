"""
Order Service — FastAPI application (v2: with JWT auth, pagination, rate limiting).

Endpoints:
  POST /api/v1/orders          — Create an order (requires JWT + Idempotency-Key)
  GET  /api/v1/orders          — List orders for current user (paginated, filterable)
  GET  /api/v1/orders/{id}     — Get order by ID (scoped to current user)
  PATCH /orders/{id}           — Update order status (internal only — saga orchestrator)
"""

import json
import math
import os
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status

from contracts.auth import AuthContext, UserRole
from contracts.events import EventEnvelope, EventType
from contracts.order import CreateOrderRequest, OrderResponse, OrderStatus
from core.auth_middleware import get_current_user, get_optional_user, require_role
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


# ── Create Order (POST /api/v1/orders) ───────────────────────────────────────

@app.post("/api/v1/orders", response_model=OrderResponse, status_code=status.HTTP_202_ACCEPTED)
def create_order(
    request: CreateOrderRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_user),
):
    """Create a new order with atomic outbox event write.

    Requires: valid JWT (customer or admin role).
    The customer_id is taken from the JWT, not from the request body —
    a user can only create orders for themselves.
    """

    # Check idempotency
    cached = idem_store.get(idempotency_key)
    if cached:
        return OrderResponse(**cached["response"])

    order_id = f"ORD-{uuid.uuid4().hex[:12].upper()}"

    with get_session(SessionFactory) as session:
        # Write order row — customer_id comes from JWT, not request
        order = Order(
            order_id=order_id,
            customer_id=auth.user_id,  # From JWT, not client input
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
                "customer_id": auth.user_id,
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

    response = OrderResponse(
        order_id=order_id,
        status=OrderStatus.CREATED,
        total_amount=request.total_amount,
    )

    # Cache for idempotent replays
    idem_store.set(idempotency_key, response.model_dump(), status_code=202)

    logger.info(f"Order {order_id} created by user {auth.user_id}")
    return response


# ── List Orders with Pagination (GET /api/v1/orders) ────────────────────────

@app.get("/api/v1/orders")
def list_orders(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(default=10, ge=1, le=100, description="Items per page (max 100)"),
    order_status: str | None = Query(default=None, alias="status", description="Filter by status"),
    sort: str = Query(default="-created_at", description="Sort field. Prefix with - for descending"),
    auth: AuthContext = Depends(get_current_user),
):
    """List orders for the current user, with pagination and filtering.

    Pagination response format:
    {
        "items": [...],
        "total": 47,
        "page": 2,
        "limit": 10,
        "pages": 5,
        "has_next": true,
        "has_prev": true
    }

    Example: GET /api/v1/orders?page=2&limit=10&status=CONFIRMED&sort=-created_at
    """
    with get_session(SessionFactory) as session:
        # Base query — scoped to current user (customer sees only their orders)
        query = session.query(Order)

        if auth.role == UserRole.CUSTOMER:
            query = query.filter(Order.customer_id == auth.user_id)
        # Admin sees all orders (no filter)

        # Apply status filter
        if order_status:
            query = query.filter(Order.status == order_status.upper())

        # Apply sort
        descending = sort.startswith("-")
        sort_field = sort.lstrip("-")
        sort_column = getattr(Order, sort_field, Order.created_at)
        if descending:
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

        # Count total
        total = query.count()

        # Apply pagination
        offset = (page - 1) * limit
        orders = query.offset(offset).limit(limit).all()

        # Build response
        items = [
            OrderResponse(
                order_id=o.order_id,
                status=OrderStatus(o.status) if o.status in [s.value for s in OrderStatus] else OrderStatus.CREATED,
                total_amount=o.total_amount,
                eta_minutes=o.eta_minutes,
                eta_lower=o.eta_lower,
                eta_upper=o.eta_upper,
                degraded=bool(o.degraded),
            ).model_dump()
            for o in orders
        ]

        pages = math.ceil(total / limit) if total > 0 else 1

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
            "has_next": page < pages,
            "has_prev": page > 1,
        }


# ── Get Single Order (GET /api/v1/orders/{id}) ──────────────────────────────

@app.get("/api/v1/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str, auth: AuthContext = Depends(get_current_user)):
    """Retrieve an order by its ID. Scoped to the current user."""
    with get_session(SessionFactory) as session:
        query = session.query(Order).filter(Order.order_id == order_id)

        # Customers can only see their own orders
        if auth.role == UserRole.CUSTOMER:
            query = query.filter(Order.customer_id == auth.user_id)

        order = query.first()
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

        return OrderResponse(
            order_id=order.order_id,
            status=OrderStatus(order.status) if order.status in [s.value for s in OrderStatus] else OrderStatus.CREATED,
            total_amount=order.total_amount,
            eta_minutes=order.eta_minutes,
            eta_lower=order.eta_lower,
            eta_upper=order.eta_upper,
            degraded=bool(order.degraded),
        )


# ── Internal: Update Order Status (PATCH /orders/{id}) ──────────────────────
# This endpoint is called by the saga orchestrator over the internal network.
# No JWT required — internal-only routes are reachable only on the compose network.

@app.patch("/orders/{order_id}")
def update_order_status(
    order_id: str,
    new_status: str,
    eta_minutes: float | None = None,
    eta_lower: float | None = None,
    eta_upper: float | None = None,
    degraded: bool = False,
):
    """Update order status — called by the saga orchestrator (internal)."""
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


# ── Backward compatibility: old /orders POST route (used by saga/Streamlit) ──

@app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_202_ACCEPTED)
def create_order_legacy(
    request: CreateOrderRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    auth: AuthContext | None = Depends(get_optional_user),
):
    """Legacy endpoint — works with or without auth for backward compatibility."""
    order_id = f"ORD-{uuid.uuid4().hex[:12].upper()}"
    customer_id = auth.user_id if auth else request.customer_id

    # Check idempotency
    cached = idem_store.get(idempotency_key)
    if cached:
        return OrderResponse(**cached["response"])

    with get_session(SessionFactory) as session:
        order = Order(
            order_id=order_id,
            customer_id=customer_id,
            restaurant_id=request.restaurant_id,
            items=json.dumps(request.items),
            total_amount=request.total_amount,
            status=OrderStatus.CREATED.value,
            idempotency_key=idempotency_key,
        )
        session.add(order)

        event = EventEnvelope(
            event_type=EventType.ORDER_CREATED,
            correlation_id=order_id,
            idempotency_key=idempotency_key,
            payload={
                "order_id": order_id,
                "customer_id": customer_id,
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

    response = OrderResponse(
        order_id=order_id,
        status=OrderStatus.CREATED,
        total_amount=request.total_amount,
    )
    idem_store.set(idempotency_key, response.model_dump(), status_code=202)
    logger.info(f"Order {order_id} created (legacy route) for {customer_id}")
    return response


@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order_legacy(order_id: str):
    """Legacy endpoint without auth."""
    with get_session(SessionFactory) as session:
        order = session.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        return OrderResponse(
            order_id=order.order_id,
            status=OrderStatus(order.status) if order.status in [s.value for s in OrderStatus] else OrderStatus.CREATED,
            total_amount=order.total_amount,
            eta_minutes=order.eta_minutes,
            eta_lower=order.eta_lower,
            eta_upper=order.eta_upper,
            degraded=bool(order.degraded),
        )
