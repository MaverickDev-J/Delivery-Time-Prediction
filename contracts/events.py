import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

EVENT_SCHEMA_VERSION = "1.0.0"


class EventType(str, Enum):
    ORDER_CREATED = "order.created"
    PAYMENT_AUTHORIZED = "payment.authorized"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_REFUNDED = "payment.refunded"
    INVENTORY_RESERVED = "inventory.reserved"
    INVENTORY_OUT_OF_STOCK = "inventory.out_of_stock"
    INVENTORY_RELEASED = "inventory.released"
    ETA_PREDICTED = "eta.predicted"
    ORDER_CONFIRMED = "order.confirmed"
    ORDER_CANCELLED = "order.cancelled"
    ORDER_DELIVERED = "order.delivered"


class EventEnvelope(BaseModel):
    """Standardized event envelope across all services."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique event ID")
    event_type: EventType = Field(..., description="Type of event")
    event_version: str = Field(default=EVENT_SCHEMA_VERSION, description="Schema version of event payload")
    occurred_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 UTC timestamp of occurrence"
    )
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Distributed trace/correlation ID")
    idempotency_key: str | None = Field(default=None, description="Idempotency key associated with the transaction")
    traceparent: str | None = Field(default=None, description="W3C traceparent header for distributed tracing across stream hops")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event specific payload")

    def to_stream_dict(self) -> dict[str, str]:
        """Convert envelope to Redis Stream key-value string dictionary."""
        import json
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value if isinstance(self.event_type, EventType) else str(self.event_type),
            "event_version": self.event_version,
            "occurred_at": self.occurred_at,
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key or "",
            "traceparent": self.traceparent or "",
            "payload": json.dumps(self.payload),
        }

    @classmethod
    def from_stream_dict(cls, stream_dict: dict[str, Any]) -> "EventEnvelope":
        """Deserialize from Redis Stream dictionary."""
        import json
        payload_raw = stream_dict.get("payload", "{}")
        if isinstance(payload_raw, bytes):
            payload_raw = payload_raw.decode("utf-8")
        payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw

        return cls(
            event_id=stream_dict.get("event_id", str(uuid.uuid4())),
            event_type=EventType(stream_dict.get("event_type")),
            event_version=stream_dict.get("event_version", EVENT_SCHEMA_VERSION),
            occurred_at=stream_dict.get("occurred_at", datetime.now(UTC).isoformat()),
            correlation_id=stream_dict.get("correlation_id", str(uuid.uuid4())),
            idempotency_key=stream_dict.get("idempotency_key") or None,
            traceparent=stream_dict.get("traceparent") or None,
            payload=payload,
        )
