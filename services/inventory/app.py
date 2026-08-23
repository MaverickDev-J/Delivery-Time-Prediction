"""
Inventory Service — reserve and release stock.

Uses atomic stock decrement with row-level check to prevent over-reservation.
"""

import json
import os
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, String, Text

from contracts.inventory import (
    InventoryStatus,
    ReleaseStockRequest,
    ReservationResponse,
    ReserveStockRequest,
)
from core.database import Base, create_db_engine, create_session_factory, get_session, init_tables
from core.idempotency import IdempotencyStore
from core.logging import setup_logger
from core.metrics import add_metrics_middleware, expose_metrics

logger = setup_logger("inventory-service", service_name="inventory-service")

# Database
DATABASE_URL = os.getenv("INVENTORY_DATABASE_URL", "sqlite:///data/inventory.db")
engine = create_db_engine(DATABASE_URL)
SessionFactory = create_session_factory(engine)


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(64), unique=True, nullable=False)
    name = Column(String(128), nullable=False)
    stock = Column(Integer, nullable=False, default=100)


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reservation_id = Column(String(64), unique=True, nullable=False)
    order_id = Column(String(64), nullable=False)
    items = Column(Text, nullable=False)  # JSON list
    status = Column(String(32), nullable=False)
    idempotency_key = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


init_tables(engine, Base)

# Seed default inventory items if empty
with get_session(SessionFactory) as session:
    if session.query(InventoryItem).count() == 0:
        default_items = [
            InventoryItem(item_id=f"ITEM-{i}", name=f"Menu Item {i}", stock=100)
            for i in range(1, 21)
        ]
        session.add_all(default_items)
        logger.info("Seeded 20 default inventory items")

# Idempotency
idem_store = IdempotencyStore()

app = FastAPI(title="DeliverIQ Inventory Service", version="1.0.0")
add_metrics_middleware(app, service_name="inventory")
expose_metrics(app)


@app.get("/health")
def health():
    return {"status": "UP", "service": "inventory-service"}


class SetStockRequest(BaseModel):
    item_id: str
    stock: int


@app.post("/inventory/set-stock")
def set_stock(req: SetStockRequest):
    """Set stock for an item (used by flash sale race tests)."""
    with get_session(SessionFactory) as session:
        item = session.query(InventoryItem).filter(InventoryItem.item_id == req.item_id).with_for_update().first()
        if not item:
            item = InventoryItem(item_id=req.item_id, name=f"Flash Item {req.item_id}", stock=req.stock)
            session.add(item)
        else:
            item.stock = req.stock
    return {"status": "OK", "item_id": req.item_id, "stock": req.stock}


@app.get("/inventory/stock/{item_id}")
def get_item_stock(item_id: str):
    """Get live stock for an item."""
    with get_session(SessionFactory) as session:
        item = session.query(InventoryItem).filter(InventoryItem.item_id == item_id).first()
        return {"item_id": item_id, "stock": item.stock if item else 0}


@app.post("/inventory/reserve", response_model=ReservationResponse)
def reserve_stock(request: ReserveStockRequest):
    """Reserve stock for an order. Atomic row-locked decrement."""

    cached = idem_store.get(request.idempotency_key)
    if cached:
        return ReservationResponse(**cached["response"])

    reservation_id = f"RSV-{uuid.uuid4().hex[:12].upper()}"

    with get_session(SessionFactory) as session:
        # Check all items have sufficient stock with row lock
        for item_id in request.items:
            item = session.query(InventoryItem).filter(InventoryItem.item_id == item_id).with_for_update().first()
            if not item or item.stock <= 0:
                # Out of stock — do NOT reserve anything
                response = ReservationResponse(
                    reservation_id=reservation_id,
                    order_id=request.order_id,
                    status=InventoryStatus.OUT_OF_STOCK,
                    items=request.items,
                    idempotency_key=request.idempotency_key,
                    message=f"Item {item_id} is out of stock",
                )
                idem_store.set(request.idempotency_key, response.model_dump())
                logger.warning(f"Reservation {reservation_id} failed: {item_id} out of stock")
                return response

        # All items available — decrement stock atomically
        for item_id in request.items:
            item = session.query(InventoryItem).filter(InventoryItem.item_id == item_id).with_for_update().first()
            item.stock -= 1

        # Record reservation
        reservation = Reservation(
            reservation_id=reservation_id,
            order_id=request.order_id,
            items=json.dumps(request.items),
            status=InventoryStatus.RESERVED.value,
            idempotency_key=request.idempotency_key,
        )
        session.add(reservation)

    response = ReservationResponse(
        reservation_id=reservation_id,
        order_id=request.order_id,
        status=InventoryStatus.RESERVED,
        items=request.items,
        idempotency_key=request.idempotency_key,
        message="Stock reserved successfully",
    )

    idem_store.set(request.idempotency_key, response.model_dump())
    logger.info(f"Reservation {reservation_id} created for order {request.order_id}")
    return response


@app.post("/inventory/release", response_model=ReservationResponse)
def release_stock(request: ReleaseStockRequest):
    """Release previously reserved stock (compensating action)."""

    cached = idem_store.get(request.idempotency_key)
    if cached:
        return ReservationResponse(**cached["response"])

    with get_session(SessionFactory) as session:
        reservation = (
            session.query(Reservation)
            .filter(Reservation.reservation_id == request.reservation_id)
            .first()
        )
        if not reservation:
            raise HTTPException(status_code=404, detail=f"Reservation {request.reservation_id} not found")

        # Restore stock
        items = json.loads(reservation.items)
        for item_id in items:
            item = session.query(InventoryItem).filter(InventoryItem.item_id == item_id).first()
            if item:
                item.stock += 1

        reservation.status = InventoryStatus.RELEASED.value

    response = ReservationResponse(
        reservation_id=request.reservation_id,
        order_id=request.order_id,
        status=InventoryStatus.RELEASED,
        items=items,
        idempotency_key=request.idempotency_key,
        message="Stock released (compensating action)",
    )

    idem_store.set(request.idempotency_key, response.model_dump())
    logger.info(f"Reservation {request.reservation_id} released for order {request.order_id}")
    return response
