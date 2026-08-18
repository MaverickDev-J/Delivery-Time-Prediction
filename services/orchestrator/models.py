"""
Saga Orchestrator database models.

Tables:
  - saga_instances: One row per saga (order), tracks current state
  - saga_step_logs: Append-only log of every state transition
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from core.database import Base


class SagaInstance(Base):
    __tablename__ = "saga_instances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    saga_id = Column(String(64), unique=True, nullable=False, default=lambda: f"SAGA-{uuid.uuid4().hex[:12].upper()}")
    order_id = Column(String(64), unique=True, nullable=False)
    correlation_id = Column(String(64), nullable=False)
    current_state = Column(String(48), nullable=False, default="CREATED")

    # Artifacts collected during forward steps
    payment_id = Column(String(64), nullable=True)
    reservation_id = Column(String(64), nullable=True)
    refund_id = Column(String(64), nullable=True)
    eta_minutes = Column(Float, nullable=True)
    eta_lower = Column(Float, nullable=True)
    eta_upper = Column(Float, nullable=True)
    degraded = Column(Integer, nullable=False, default=0)

    # Timing
    started_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    completed_at = Column(DateTime, nullable=True)

    # Error tracking
    error_reason = Column(Text, nullable=True)


class SagaStepLog(Base):
    __tablename__ = "saga_step_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    saga_id = Column(String(64), nullable=False, index=True)
    step_name = Column(String(48), nullable=False)
    from_state = Column(String(48), nullable=False)
    to_state = Column(String(48), nullable=False)
    step_type = Column(String(16), nullable=False, default="FORWARD")  # FORWARD or COMPENSATE
    detail = Column(Text, nullable=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
