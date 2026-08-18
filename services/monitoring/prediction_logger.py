"""
Prediction logger for the ML Monitoring Service.

Persists every ETA prediction and handles delayed-label joins when
order.delivered events arrive.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from services.monitoring.models import PredictionLog


def log_prediction(
    session: Session,
    *,
    order_id: str,
    model_version: str,
    feature_schema_version: str,
    input_features: dict,
    eta_minutes: float,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
    degraded: bool = False,
    correlation_id: str | None = None,
) -> PredictionLog:
    """Persist a prediction to the monitoring database."""
    log = PredictionLog(
        prediction_id=f"PRED-{uuid.uuid4().hex[:12].upper()}",
        order_id=order_id,
        correlation_id=correlation_id,
        model_version=model_version,
        feature_schema_version=feature_schema_version,
        input_features=input_features,
        eta_minutes=eta_minutes,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        degraded=degraded,
        predicted_at=datetime.now(UTC),
    )
    session.add(log)
    session.flush()
    return log


def join_actual(
    session: Session,
    *,
    order_id: str,
    actual_minutes: float,
) -> PredictionLog | None:
    """Join a delayed actual delivery time onto the prediction row.

    Returns the updated row, or None if no matching prediction is found.
    Handles the 'unmatched' case (cancelled/never delivered) explicitly.
    """
    log = session.query(PredictionLog).filter(
        PredictionLog.order_id == order_id,
        PredictionLog.actual_minutes.is_(None),  # Only join once
    ).first()

    if log is None:
        return None

    now = datetime.now(UTC)
    log.actual_minutes = actual_minutes
    log.delivered_at = now
    if log.predicted_at:
        log.label_lag_seconds = (now - log.predicted_at).total_seconds()
    session.flush()
    return log


def get_labelled_predictions(
    session: Session,
    *,
    limit: int = 500,
) -> list[PredictionLog]:
    """Return the most recent predictions that have actual delivery times joined."""
    return (
        session.query(PredictionLog)
        .filter(PredictionLog.actual_minutes.is_not(None))
        .order_by(PredictionLog.predicted_at.desc())
        .limit(limit)
        .all()
    )


def get_recent_predictions(
    session: Session,
    *,
    limit: int = 500,
) -> list[PredictionLog]:
    """Return the most recent predictions (labelled or not)."""
    return (
        session.query(PredictionLog)
        .order_by(PredictionLog.predicted_at.desc())
        .limit(limit)
        .all()
    )
