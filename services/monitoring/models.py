"""
SQLAlchemy models for the ML Monitoring Service.

Stores prediction logs, drift reports, and retrain gate decisions.
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class MonitoringBase(DeclarativeBase):
    pass


class PredictionLog(MonitoringBase):
    """Stores every ETA prediction for monitoring, drift detection, and performance tracking."""
    __tablename__ = "prediction_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prediction_id = Column(String(64), unique=True, nullable=False, index=True)
    order_id = Column(String(64), nullable=False, index=True)
    correlation_id = Column(String(64), nullable=True)
    model_version = Column(String(32), nullable=False)
    feature_schema_version = Column(String(16), nullable=False)
    input_features = Column(JSON, nullable=False)
    eta_minutes = Column(Float, nullable=False)
    lower_bound = Column(Float, nullable=True)
    upper_bound = Column(Float, nullable=True)
    degraded = Column(Boolean, default=False)
    predicted_at = Column(DateTime, default=lambda: datetime.now(UTC))

    # Delayed label fields — joined when order.delivered event arrives
    actual_minutes = Column(Float, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    label_lag_seconds = Column(Float, nullable=True)


class DriftReport(MonitoringBase):
    """Stores per-feature drift detection results (PSI scores)."""
    __tablename__ = "drift_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(String(64), unique=True, nullable=False)
    feature_name = Column(String(64), nullable=False, index=True)
    psi_score = Column(Float, nullable=False)
    threshold = Column(Float, default=0.2)
    is_drifted = Column(Boolean, default=False)
    sample_size = Column(Integer, nullable=False)
    computed_at = Column(DateTime, default=lambda: datetime.now(UTC))


class RetrainDecision(MonitoringBase):
    """Audit log for every retrain gate evaluation — including suppressed decisions."""
    __tablename__ = "retrain_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    decision_id = Column(String(64), unique=True, nullable=False)
    drift_detected = Column(Boolean, nullable=False)
    perf_degraded = Column(Boolean, nullable=False)
    sample_count = Column(Integer, nullable=False)
    cooldown_ok = Column(Boolean, nullable=False)
    gate_result = Column(String(16), nullable=False)  # TRIGGERED or SUPPRESSED
    reason = Column(Text, nullable=False)
    details = Column(JSON, nullable=True)
    decided_at = Column(DateTime, default=lambda: datetime.now(UTC))
