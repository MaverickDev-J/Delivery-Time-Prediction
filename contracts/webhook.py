"""
Webhook contracts — schemas for subscriptions, delivery logs, and payloads.

Used by:
  - services/webhook/ (dispatcher & management API)
  - Ops Console (delivery log viewer & manual redelivery trigger)
  - External Merchants receiving webhook callbacks
"""

from enum import Enum
from pydantic import BaseModel, Field, HttpUrl


class WebhookStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


class WebhookSubscriptionCreate(BaseModel):
    url: str = Field(..., description="Target HTTPS/HTTP webhook callback URL", examples=["https://merchant.example.com/webhooks/deliveriq"])
    event_types: list[str] = Field(
        default=["order.created", "order.confirmed", "order.cancelled"],
        description="Event types to subscribe to",
    )
    description: str | None = Field(default=None, description="Optional label for the endpoint")


class WebhookSubscriptionResponse(BaseModel):
    id: str
    tenant_id: str
    url: str
    event_types: list[str]
    secret: str = Field(..., description="Secret used to sign payloads sent to this endpoint")
    is_active: bool
    created_at: str


class WebhookDeliveryResponse(BaseModel):
    id: str
    tenant_id: str
    subscription_id: str
    event_id: str
    event_type: str
    url: str
    payload: dict
    status_code: int | None
    attempt_count: int
    response_time_ms: float | None
    next_retry_at: str | None
    status: WebhookStatus
    error_message: str | None
    created_at: str
