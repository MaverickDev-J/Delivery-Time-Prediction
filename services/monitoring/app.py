"""
ML Monitoring Service — FastAPI application.

Provides endpoints for prediction logging, delayed-label joining,
drift reporting, rolling performance, and retrain gate evaluation.
"""

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.database import create_engine_factory, get_session, init_tables
from core.metrics import add_metrics_middleware, expose_metrics
from services.monitoring.models import MonitoringBase

# ── Database setup ───────────────────────────────────────────────────────────

DB_URL = os.environ.get("MONITORING_DB_URL", "sqlite:///data/monitoring.db")
engine_factory = create_engine_factory(DB_URL)
init_tables(engine_factory(), MonitoringBase)

# ── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(title="DeliverIQ Monitoring Service", version="1.0.0")
add_metrics_middleware(app, service_name="monitoring")
expose_metrics(app)


# ── Request/Response schemas ─────────────────────────────────────────────────

class LogPredictionRequest(BaseModel):
    order_id: str
    model_version: str = "1.0.0"
    feature_schema_version: str = "1.0.0"
    input_features: dict
    eta_minutes: float
    lower_bound: float | None = None
    upper_bound: float | None = None
    degraded: bool = False
    correlation_id: str | None = None


class LogActualRequest(BaseModel):
    order_id: str
    actual_minutes: float


class DriftCheckRequest(BaseModel):
    reference_data: dict[str, list[float]]
    current_data: dict[str, list[float]]
    threshold: float = Field(default=0.2, ge=0.0, le=1.0)


class GateConfigRequest(BaseModel):
    psi_threshold: float = 0.2
    mae_degradation_factor: float = 1.15
    baseline_mae: float = 7.5
    late_rate_threshold: float = 0.20
    min_samples: int = 200
    cooldown_seconds: float = 3600.0


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "UP", "service": "monitoring"}


@app.post("/monitoring/log-prediction", status_code=201)
def log_prediction_endpoint(req: LogPredictionRequest):
    """Log an ETA prediction for monitoring."""
    from services.monitoring.prediction_logger import log_prediction

    with get_session(engine_factory()) as session:
        log = log_prediction(
            session,
            order_id=req.order_id,
            model_version=req.model_version,
            feature_schema_version=req.feature_schema_version,
            input_features=req.input_features,
            eta_minutes=req.eta_minutes,
            lower_bound=req.lower_bound,
            upper_bound=req.upper_bound,
            degraded=req.degraded,
            correlation_id=req.correlation_id,
        )
        return {"prediction_id": log.prediction_id, "order_id": log.order_id}


@app.post("/monitoring/log-actual")
def log_actual_endpoint(req: LogActualRequest):
    """Join a delayed actual delivery time onto the prediction row."""
    from services.monitoring.prediction_logger import join_actual

    with get_session(engine_factory()) as session:
        result = join_actual(session, order_id=req.order_id, actual_minutes=req.actual_minutes)
        if result is None:
            raise HTTPException(status_code=404, detail=f"No unmatched prediction found for order {req.order_id}")
        return {
            "prediction_id": result.prediction_id,
            "order_id": result.order_id,
            "actual_minutes": result.actual_minutes,
            "label_lag_seconds": result.label_lag_seconds,
        }


@app.post("/monitoring/drift-check")
def drift_check_endpoint(req: DriftCheckRequest):
    """Run drift detection (PSI) across provided features."""
    from services.monitoring.drift_detector import run_drift_check

    with get_session(engine_factory()) as session:
        reports = run_drift_check(
            session,
            reference_data=req.reference_data,
            current_data=req.current_data,
            threshold=req.threshold,
        )
        return {
            "reports": [
                {
                    "feature_name": r.feature_name,
                    "psi_score": r.psi_score,
                    "is_drifted": r.is_drifted,
                    "sample_size": r.sample_size,
                }
                for r in reports
            ]
        }


@app.get("/monitoring/drift-report")
def drift_report_endpoint():
    """Get the most recent drift reports."""
    from services.monitoring.drift_detector import get_latest_drift_reports

    with get_session(engine_factory()) as session:
        reports = get_latest_drift_reports(session)
        return {
            "reports": [
                {
                    "feature_name": r.feature_name,
                    "psi_score": r.psi_score,
                    "is_drifted": r.is_drifted,
                    "sample_size": r.sample_size,
                    "computed_at": str(r.computed_at),
                }
                for r in reports
            ]
        }


@app.get("/monitoring/performance")
def performance_endpoint():
    """Get rolling MAE, late-rate, and interval coverage."""
    from services.monitoring.performance_tracker import compute_rolling_metrics

    with get_session(engine_factory()) as session:
        metrics = compute_rolling_metrics(session)
        return {
            "mae": metrics.mae,
            "late_rate": metrics.late_rate,
            "interval_coverage": metrics.interval_coverage,
            "sample_count": metrics.sample_count,
            "labelled_count": metrics.labelled_count,
        }


@app.get("/monitoring/retrain-decisions")
def retrain_decisions_endpoint():
    """Get audit log of retrain gate evaluations."""
    from services.monitoring.models import RetrainDecision

    with get_session(engine_factory()) as session:
        decisions = (
            session.query(RetrainDecision)
            .order_by(RetrainDecision.decided_at.desc())
            .limit(20)
            .all()
        )
        return {
            "decisions": [
                {
                    "decision_id": d.decision_id,
                    "gate_result": d.gate_result,
                    "drift_detected": d.drift_detected,
                    "perf_degraded": d.perf_degraded,
                    "sample_count": d.sample_count,
                    "cooldown_ok": d.cooldown_ok,
                    "reason": d.reason,
                    "decided_at": str(d.decided_at),
                }
                for d in decisions
            ]
        }


@app.post("/monitoring/evaluate-gate")
def evaluate_gate_endpoint(config: GateConfigRequest | None = None):
    """Manually trigger a retrain gate evaluation."""
    from services.monitoring.drift_detector import get_latest_drift_reports
    from services.monitoring.performance_tracker import compute_rolling_metrics
    from services.monitoring.retrain_gate import GateConfig, evaluate_gate

    gate_config = None
    if config:
        gate_config = GateConfig(
            psi_threshold=config.psi_threshold,
            mae_degradation_factor=config.mae_degradation_factor,
            baseline_mae=config.baseline_mae,
            late_rate_threshold=config.late_rate_threshold,
            min_samples=config.min_samples,
            cooldown_seconds=config.cooldown_seconds,
        )

    with get_session(engine_factory()) as session:
        drift_reports = get_latest_drift_reports(session)
        performance = compute_rolling_metrics(session)
        result = evaluate_gate(session, drift_reports, performance, gate_config)
        return {
            "triggered": result.triggered,
            "reason": result.reason,
            "details": result.details,
        }
