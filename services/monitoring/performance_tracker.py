"""
Rolling performance tracker for the ML Monitoring Service.

Computes MAE, late-rate, and interval coverage on a sliding window
of labelled predictions (predictions where actual delivery time has arrived).
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from services.monitoring.models import PredictionLog

LATE_THRESHOLD_MINUTES = 5.0  # actual > predicted + this = "late"


@dataclass
class PerformanceMetrics:
    """Rolling performance metrics computed from labelled predictions."""
    mae: float
    late_rate: float
    interval_coverage: float
    sample_count: int
    labelled_count: int


def compute_rolling_metrics(
    session: Session,
    window_size: int = 200,
) -> PerformanceMetrics:
    """Compute rolling performance metrics from the most recent labelled predictions.

    Args:
        session: DB session.
        window_size: Number of most recent labelled predictions to evaluate.

    Returns:
        PerformanceMetrics with MAE, late-rate, interval coverage.
    """
    labelled = (
        session.query(PredictionLog)
        .filter(PredictionLog.actual_minutes.is_not(None))
        .order_by(PredictionLog.predicted_at.desc())
        .limit(window_size)
        .all()
    )

    total = (
        session.query(PredictionLog)
        .order_by(PredictionLog.predicted_at.desc())
        .limit(window_size)
        .count()
    )

    if not labelled:
        return PerformanceMetrics(
            mae=0.0,
            late_rate=0.0,
            interval_coverage=0.0,
            sample_count=total,
            labelled_count=0,
        )

    errors = []
    late_count = 0
    in_interval_count = 0
    has_interval_count = 0

    for pred in labelled:
        error = abs(pred.actual_minutes - pred.eta_minutes)
        errors.append(error)

        # Late = actual > predicted + threshold
        if pred.actual_minutes > pred.eta_minutes + LATE_THRESHOLD_MINUTES:
            late_count += 1

        # Interval coverage (only if bounds exist)
        if pred.lower_bound is not None and pred.upper_bound is not None:
            has_interval_count += 1
            if pred.lower_bound <= pred.actual_minutes <= pred.upper_bound:
                in_interval_count += 1

    mae = sum(errors) / len(errors)
    late_rate = late_count / len(labelled)
    interval_coverage = (
        in_interval_count / has_interval_count if has_interval_count > 0 else 0.0
    )

    return PerformanceMetrics(
        mae=round(mae, 4),
        late_rate=round(late_rate, 4),
        interval_coverage=round(interval_coverage, 4),
        sample_count=total,
        labelled_count=len(labelled),
    )
