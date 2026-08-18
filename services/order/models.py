"""
Order Service database models.

Tables:
  - orders: Core order records
  - outbox_events: Transactional outbox (shared schema from core.outbox)
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from core.database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), unique=True, nullable=False, default=lambda: f"ORD-{uuid.uuid4().hex[:12].upper()}")
    customer_id = Column(String(64), nullable=False)
    restaurant_id = Column(String(64), nullable=False)
    items = Column(Text, nullable=False)  # JSON list
    total_amount = Column(Float, nullable=False)
    status = Column(String(32), nullable=False, default="CREATED")
    idempotency_key = Column(String(64), unique=True, nullable=True)
    eta_minutes = Column(Float, nullable=True)
    eta_lower = Column(Float, nullable=True)
    eta_upper = Column(Float, nullable=True)
    degraded = Column(Integer, nullable=False, default=0)  # 0=false, 1=true
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
