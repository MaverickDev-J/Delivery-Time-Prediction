"""Order domain contracts."""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CONFIRMED_DEGRADED = "CONFIRMED_DEGRADED"
    CANCELLED = "CANCELLED"


class CreateOrderRequest(BaseModel):
    """Payload from the client to place a new order."""
    customer_id: str = Field(..., description="Customer placing the order")
    restaurant_id: str = Field(..., description="Restaurant fulfilling the order")
    items: list[str] = Field(..., min_length=1, description="List of item IDs ordered")
    total_amount: float = Field(..., gt=0, description="Total order value in INR")

    # ETA prediction context — forwarded to ETA service
    rider_age: float = Field(default=25.0, ge=18, le=75)
    rider_ratings: float = Field(default=4.5, ge=1.0, le=5.0)
    restaurant_latitude: float = Field(default=12.97)
    restaurant_longitude: float = Field(default=77.59)
    delivery_latitude: float = Field(default=13.03)
    delivery_longitude: float = Field(default=77.60)
    weather: str = Field(default="sunny")
    traffic: str = Field(default="medium")
    vehicle_type: str = Field(default="motorcycle")
    city_type: str = Field(default="metropolitan")

    model_config = {
        "json_schema_extra": {
            "example": {
                "customer_id": "CUST-001",
                "restaurant_id": "REST-042",
                "items": ["ITEM-1", "ITEM-2"],
                "total_amount": 450.0,
            }
        }
    }


class OrderResponse(BaseModel):
    """Response after order creation."""
    order_id: str
    status: OrderStatus
    total_amount: float
    eta_minutes: float | None = None
    eta_lower: float | None = None
    eta_upper: float | None = None
    degraded: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
