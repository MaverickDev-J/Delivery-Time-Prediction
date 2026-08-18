"""
Drift detection using Population Stability Index (PSI).

PSI measures how much a feature's distribution has shifted from a reference
(training) distribution. Thresholds:
  < 0.1  — No significant drift
  0.1–0.2 — Moderate drift (monitor)
  > 0.2  — Significant drift (action required)
"""

import uuid
from datetime import UTC, datetime

import numpy as np
from sqlalchemy.orm import Session

from services.monitoring.models import DriftReport


def compute_psi(
    reference: list[float],
    current: list[float],
    bins: int = 10,
    epsilon: float = 1e-4,
) -> float:
    """Compute the Population Stability Index between two distributions.

    Args:
        reference: Reference (training) distribution values.
        current: Current (production) distribution values.
        bins: Number of histogram bins.
        epsilon: Small constant to avoid log(0).

    Returns:
        PSI score (float). Higher = more drift.
    """
    if len(reference) < bins or len(current) < bins:
        return 0.0

    # Use reference distribution to define bin edges
    breakpoints = np.linspace(
        min(min(reference), min(current)),
        max(max(reference), max(current)),
        bins + 1,
    )

    ref_counts, _ = np.histogram(reference, bins=breakpoints)
    cur_counts, _ = np.histogram(current, bins=breakpoints)

    # Normalise to proportions
    ref_proportions = (ref_counts + epsilon) / (len(reference) + epsilon * bins)
    cur_proportions = (cur_counts + epsilon) / (len(current) + epsilon * bins)

    # PSI formula: sum((current - reference) * ln(current / reference))
    psi = float(np.sum(
        (cur_proportions - ref_proportions) * np.log(cur_proportions / ref_proportions)
    ))

    return max(psi, 0.0)


def detect_drift(
    feature_name: str,
    reference: list[float],
    current: list[float],
    threshold: float = 0.2,
    bins: int = 10,
) -> dict:
    """Detect drift for a single feature.

    Returns:
        Dict with keys: feature_name, psi_score, threshold, is_drifted, sample_size
    """
    psi_score = compute_psi(reference, current, bins=bins)
    return {
        "feature_name": feature_name,
        "psi_score": round(psi_score, 6),
        "threshold": threshold,
        "is_drifted": psi_score > threshold,
        "sample_size": len(current),
    }


def run_drift_check(
    session: Session,
    reference_data: dict[str, list[float]],
    current_data: dict[str, list[float]],
    threshold: float = 0.2,
) -> list[DriftReport]:
    """Run drift detection across all features and persist results.

    Args:
        session: DB session for persisting reports.
        reference_data: {feature_name: [values...]} from training data.
        current_data: {feature_name: [values...]} from recent predictions.
        threshold: PSI threshold for drift flagging.

    Returns:
        List of DriftReport records.
    """
    reports = []
    for feature_name, ref_values in reference_data.items():
        cur_values = current_data.get(feature_name, [])

        if len(cur_values) < 10:
            continue

        result = detect_drift(feature_name, ref_values, cur_values, threshold)

        report = DriftReport(
            report_id=f"DRIFT-{uuid.uuid4().hex[:12].upper()}",
            feature_name=feature_name,
            psi_score=result["psi_score"],
            threshold=threshold,
            is_drifted=result["is_drifted"],
            sample_size=result["sample_size"],
            computed_at=datetime.now(UTC),
        )
        session.add(report)
        reports.append(report)

    session.flush()
    return reports


def get_latest_drift_reports(
    session: Session,
    limit: int = 20,
) -> list[DriftReport]:
    """Get the most recent drift reports."""
    return (
        session.query(DriftReport)
        .order_by(DriftReport.computed_at.desc())
        .limit(limit)
        .all()
    )
