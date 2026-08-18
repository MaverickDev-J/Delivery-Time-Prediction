"""
Compound retrain gate for the ML Monitoring Service.

Retraining is triggered ONLY when ALL conditions are met:
  1. Drift is significant (any feature PSI > threshold)
  2. Performance has degraded (MAE > baseline * factor OR late_rate > threshold)
  3. Enough samples have been collected (n >= min_samples)
  4. Cooldown has elapsed since last retrain

Every evaluation is logged — including suppressions — for auditability.
This prevents false-alarm-driven retraining thrash.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from services.monitoring.models import DriftReport, RetrainDecision
from services.monitoring.performance_tracker import PerformanceMetrics


@dataclass
class GateConfig:
    """Configuration for the compound retrain gate."""
    psi_threshold: float = 0.2
    mae_degradation_factor: float = 1.15  # MAE > baseline * this = degraded
    baseline_mae: float = 7.5  # Training-time MAE baseline
    late_rate_threshold: float = 0.20  # > 20% late = degraded
    min_samples: int = 200
    cooldown_seconds: float = 3600.0  # 1 hour minimum between retrains


@dataclass
class GateResult:
    """Result of a retrain gate evaluation."""
    triggered: bool
    reason: str
    details: dict


def evaluate_gate(
    session: Session,
    drift_reports: list[DriftReport],
    performance: PerformanceMetrics,
    config: GateConfig | None = None,
) -> GateResult:
    """Evaluate the compound retrain gate and log the decision.

    Args:
        session: DB session.
        drift_reports: Recent drift reports for all features.
        performance: Current rolling performance metrics.
        config: Gate configuration (uses defaults if None).

    Returns:
        GateResult indicating whether retraining was triggered.
    """
    if config is None:
        config = GateConfig()

    # --- Condition 1: Drift detected ---
    drifted_features = [r for r in drift_reports if r.is_drifted]
    drift_detected = len(drifted_features) > 0
    drifted_names = [r.feature_name for r in drifted_features]

    # --- Condition 2: Performance degraded ---
    mae_degraded = performance.mae > (config.baseline_mae * config.mae_degradation_factor)
    late_degraded = performance.late_rate > config.late_rate_threshold
    perf_degraded = mae_degraded or late_degraded

    # --- Condition 3: Enough samples ---
    enough_samples = performance.labelled_count >= config.min_samples

    # --- Condition 4: Cooldown elapsed ---
    last_trigger = (
        session.query(RetrainDecision)
        .filter(RetrainDecision.gate_result == "TRIGGERED")
        .order_by(RetrainDecision.decided_at.desc())
        .first()
    )
    now = datetime.now(UTC)
    if last_trigger and last_trigger.decided_at:
        elapsed = (now - last_trigger.decided_at).total_seconds()
        cooldown_ok = elapsed >= config.cooldown_seconds
    else:
        cooldown_ok = True  # No prior trigger

    # --- Compound decision ---
    triggered = drift_detected and perf_degraded and enough_samples and cooldown_ok

    # Build reason string
    reasons = []
    if not drift_detected:
        reasons.append("no significant drift detected")
    if not perf_degraded:
        reasons.append(f"performance within bounds (MAE={performance.mae:.2f}, late_rate={performance.late_rate:.2%})")
    if not enough_samples:
        reasons.append(f"insufficient samples ({performance.labelled_count}/{config.min_samples})")
    if not cooldown_ok:
        reasons.append("cooldown not elapsed")

    if triggered:
        reason = f"TRIGGERED: drift on {drifted_names}, MAE={performance.mae:.2f}, late_rate={performance.late_rate:.2%}"
    else:
        reason = f"SUPPRESSED: {'; '.join(reasons)}"

    details = {
        "drift_detected": drift_detected,
        "drifted_features": drifted_names,
        "mae": performance.mae,
        "late_rate": performance.late_rate,
        "interval_coverage": performance.interval_coverage,
        "labelled_count": performance.labelled_count,
        "cooldown_ok": cooldown_ok,
        "mae_threshold": config.baseline_mae * config.mae_degradation_factor,
        "late_rate_threshold": config.late_rate_threshold,
    }

    # --- Persist decision ---
    decision = RetrainDecision(
        decision_id=f"GATE-{uuid.uuid4().hex[:12].upper()}",
        drift_detected=drift_detected,
        perf_degraded=perf_degraded,
        sample_count=performance.labelled_count,
        cooldown_ok=cooldown_ok,
        gate_result="TRIGGERED" if triggered else "SUPPRESSED",
        reason=reason,
        details=details,
        decided_at=now,
    )
    session.add(decision)
    session.flush()

    return GateResult(
        triggered=triggered,
        reason=reason,
        details=details,
    )
