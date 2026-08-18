"""Inventory domain contracts."""

from enum import Enum

from pydantic import BaseModel, Field


class InventoryStatus(str, Enum):
    RESERVED = "RESERVED"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    RELEASED = "RELEASED"


class ReserveStockRequest(BaseModel):
    order_id: str = Field(..., description="Order requesting stock reservation")
    items: list[str] = Field(..., min_length=1, description="Item IDs to reserve")
    idempotency_key: str = Field(..., description="Client-generated idempotency key")


class ReleaseStockRequest(BaseModel):
    order_id: str = Field(..., description="Order releasing reserved stock")
    reservation_id: str = Field(..., description="Original reservation ID")
    idempotency_key: str = Field(..., description="Client-generated idempotency key")


class ReservationResponse(BaseModel):
    reservation_id: str
    order_id: str
    status: InventoryStatus
    items: list[str]
    idempotency_key: str
    message: str | None = None
