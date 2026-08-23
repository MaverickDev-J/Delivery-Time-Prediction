"""
Webhook Service — database models.

Tables:
  - webhook_subscriptions: merchant endpoint registrations
  - webhook_deliveries: every delivery attempt (audit trail)
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from core.database import Base


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(64), nullable=False, index=True)
    url = Column(String(512), nullable=False)
    event_types = Column(Text, nullable=False)  # JSON list: ["order.confirmed","order.cancelled"]
    secret = Column(String(128), nullable=False)  # Per-endpoint signing secret
    description = Column(String(255), nullable=True)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))


class WebhookDelivery(Base):
    """
    Append-only log of every webhook delivery attempt.
    Supports retry tracking, manual redelivery, and ops console display.
    """
    __tablename__ = "webhook_deliveries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(64), nullable=False, index=True)
    subscription_id = Column(String(36), nullable=False, index=True)
    event_id = Column(String(64), nullable=False)
    event_type = Column(String(64), nullable=False)
    url = Column(String(512), nullable=False)
    payload = Column(Text, nullable=False)  # JSON
    status_code = Column(Integer, nullable=True)  # HTTP status from merchant
    response_time_ms = Column(Float, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=1)
    max_attempts = Column(Integer, nullable=False, default=5)
    next_retry_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, SUCCESS, FAILED, RETRYING
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
