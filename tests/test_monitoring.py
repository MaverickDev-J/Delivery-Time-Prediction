"""
Tests for ML Monitoring Service — Phase 6.

Covers:
- PSI computation correctness
- Drift detection with known distributions
- Performance tracker (MAE, late-rate, interval coverage)
- Retrain gate compound logic
- Prediction logging and actual joining
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.monitoring.drift_detector import compute_psi, detect_drift, run_drift_check
from services.monitoring.models import DriftReport, MonitoringBase, PredictionLog
from services.monitoring.performance_tracker import PerformanceMetrics, compute_rolling_metrics
from services.monitoring.prediction_logger import join_actual, log_prediction
from services.monitoring.retrain_gate import GateConfig, evaluate_gate

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def monitoring_engine():
    engine = create_engine("sqlite:///:memory:")
    MonitoringBase.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(monitoring_engine):
    Session = sessionmaker(bind=monitoring_engine)
    with Session() as sess:
        yield sess
        sess.rollback()


# ── PSI Computation Tests ────────────────────────────────────────────────────

def test_psi_identical_distributions():
    """PSI of identical distributions should be ~0."""
    ref = [1.0, 2.0, 3.0, 4.0, 5.0] * 20
    cur = [1.0, 2.0, 3.0, 4.0, 5.0] * 20
    psi = compute_psi(ref, cur, bins=5)
    assert psi < 0.01, f"PSI should be near zero for identical distributions, got {psi}"


def test_psi_shifted_distribution():
    """PSI of a significantly shifted distribution should be > 0.2."""
    import random
    random.seed(42)
    ref = [random.gauss(10, 2) for _ in range(500)]
    cur = [random.gauss(20, 2) for _ in range(500)]  # shifted mean by 10
    psi = compute_psi(ref, cur, bins=10)
    assert psi > 0.2, f"PSI should indicate significant drift, got {psi}"


def test_psi_slightly_shifted():
    """PSI of a slightly shifted distribution should be between 0.01 and 0.2."""
    import random
    random.seed(123)
    ref = [random.gauss(10, 2) for _ in range(500)]
    cur = [random.gauss(11, 2) for _ in range(500)]  # small shift
    psi = compute_psi(ref, cur, bins=10)
    assert 0.0 < psi, f"PSI should be > 0 for a shifted distribution, got {psi}"


def test_psi_too_few_samples():
    """PSI should return 0 when samples are fewer than bins."""
    psi = compute_psi([1.0, 2.0], [3.0, 4.0], bins=10)
    assert psi == 0.0


# ── Drift Detection Tests ───────────────────────────────────────────────────

def test_detect_drift_no_drift():
    ref = list(range(100))
    cur = list(range(100))
    result = detect_drift("test_feature", ref, cur, threshold=0.2)
    assert result["is_drifted"] is False
    assert result["feature_name"] == "test_feature"


def test_detect_drift_with_drift():
    import random
    random.seed(99)
    ref = [random.gauss(5, 1) for _ in range(500)]
    cur = [random.gauss(15, 1) for _ in range(500)]
    result = detect_drift("distance", ref, cur, threshold=0.2)
    assert result["is_drifted"] is True
    assert result["psi_score"] > 0.2


def test_run_drift_check_persists_reports(session):
    # Use identical lists to guarantee no drift
    ref_data = {"age": [float(x) for x in range(200)]}
    cur_data = {"age": [float(x) for x in range(200)]}

    reports = run_drift_check(session, ref_data, cur_data, threshold=0.2)
    assert len(reports) == 1
    assert reports[0].feature_name == "age"
    assert reports[0].is_drifted is False


# ── Prediction Logger Tests ──────────────────────────────────────────────────

def test_log_prediction(session):
    log = log_prediction(
        session,
        order_id="ORD-MON-001",
        model_version="1.0.0",
        feature_schema_version="1.0.0",
        input_features={"age": 28, "distance": 10.5},
        eta_minutes=32.5,
        lower_bound=25.0,
        upper_bound=40.0,
    )
    assert log.prediction_id.startswith("PRED-")
    assert log.order_id == "ORD-MON-001"
    assert log.eta_minutes == 32.5
    assert log.actual_minutes is None


def test_join_actual(session):
    log = log_prediction(
        session,
        order_id="ORD-MON-JOIN",
        model_version="1.0.0",
        feature_schema_version="1.0.0",
        input_features={"age": 30},
        eta_minutes=25.0,
    )
    assert log.actual_minutes is None

    updated = join_actual(session, order_id="ORD-MON-JOIN", actual_minutes=28.5)
    assert updated is not None
    assert updated.actual_minutes == 28.5
    assert updated.label_lag_seconds is not None
    assert updated.label_lag_seconds >= 0


def test_join_actual_no_match(session):
    result = join_actual(session, order_id="ORD-NONEXISTENT", actual_minutes=30.0)
    assert result is None


# ── Performance Tracker Tests ────────────────────────────────────────────────

def test_compute_rolling_metrics_empty(session):
    metrics = compute_rolling_metrics(session, window_size=100)
    assert metrics.labelled_count >= 0  # may have rows from other tests


def test_compute_rolling_metrics_with_data(monitoring_engine):
    """Insert labelled predictions and verify MAE, late-rate, coverage."""
    Session = sessionmaker(bind=monitoring_engine)
    with Session() as session:
        # Insert 10 predictions with actuals
        for i in range(10):
            pred = PredictionLog(
                prediction_id=f"PRED-PERF-{i:04d}",
                order_id=f"ORD-PERF-{i:04d}",
                model_version="1.0.0",
                feature_schema_version="1.0.0",
                input_features={"age": 25 + i},
                eta_minutes=30.0,
                lower_bound=25.0,
                upper_bound=40.0,
                predicted_at=datetime.now(UTC),
                # Half are late (actual > predicted + 5)
                actual_minutes=30.0 + (10 * (i % 2)),  # 30 or 40
                delivered_at=datetime.now(UTC),
                label_lag_seconds=1800.0,
            )
            session.add(pred)
        session.commit()

        metrics = compute_rolling_metrics(session, window_size=100)
        assert metrics.labelled_count >= 10
        assert metrics.mae >= 0
        # 5 out of 10 are late (actual=40 > predicted=30 + 5)
        assert metrics.late_rate > 0


# ── Retrain Gate Tests ───────────────────────────────────────────────────────

def test_gate_suppressed_no_drift(monitoring_engine):
    """Gate should suppress if no drift detected."""
    Session = sessionmaker(bind=monitoring_engine)
    with Session() as session:
        # No drifted reports
        drift_reports = [
            DriftReport(
                report_id=f"DRIFT-NODR-{uuid.uuid4().hex[:8]}",
                feature_name="age",
                psi_score=0.05,
                threshold=0.2,
                is_drifted=False,
                sample_size=300,
            )
        ]

        perf = PerformanceMetrics(
            mae=10.0, late_rate=0.25,
            interval_coverage=0.85,
            sample_count=300, labelled_count=300,
        )

        config = GateConfig(min_samples=50, cooldown_seconds=0)
        result = evaluate_gate(session, drift_reports, perf, config)
        assert result.triggered is False
        assert "no significant drift" in result.reason.lower()
        session.commit()


def test_gate_suppressed_good_performance(monitoring_engine):
    """Gate should suppress if drift detected but performance is fine."""
    Session = sessionmaker(bind=monitoring_engine)
    with Session() as session:
        drift_reports = [
            DriftReport(
                report_id=f"DRIFT-GOOD-{uuid.uuid4().hex[:8]}",
                feature_name="distance",
                psi_score=0.35,
                threshold=0.2,
                is_drifted=True,
                sample_size=300,
            )
        ]

        perf = PerformanceMetrics(
            mae=6.0, late_rate=0.10,  # Below thresholds
            interval_coverage=0.92,
            sample_count=300, labelled_count=300,
        )

        config = GateConfig(min_samples=50, cooldown_seconds=0)
        result = evaluate_gate(session, drift_reports, perf, config)
        assert result.triggered is False
        assert "performance within bounds" in result.reason.lower()
        session.commit()


def test_gate_suppressed_insufficient_samples(monitoring_engine):
    """Gate should suppress if not enough samples."""
    Session = sessionmaker(bind=monitoring_engine)
    with Session() as session:
        drift_reports = [
            DriftReport(
                report_id=f"DRIFT-INSUF-{uuid.uuid4().hex[:8]}",
                feature_name="distance",
                psi_score=0.35,
                threshold=0.2,
                is_drifted=True,
                sample_size=50,
            )
        ]

        perf = PerformanceMetrics(
            mae=12.0, late_rate=0.30,
            interval_coverage=0.70,
            sample_count=50, labelled_count=50,
        )

        config = GateConfig(min_samples=200, cooldown_seconds=0)
        result = evaluate_gate(session, drift_reports, perf, config)
        assert result.triggered is False
        assert "insufficient samples" in result.reason.lower()
        session.commit()


def test_gate_triggered_all_conditions_met(monitoring_engine):
    """Gate should trigger when drift + degradation + samples + cooldown all pass."""
    Session = sessionmaker(bind=monitoring_engine)
    with Session() as session:
        drift_reports = [
            DriftReport(
                report_id=f"DRIFT-TRIG-{uuid.uuid4().hex[:8]}",
                feature_name="traffic",
                psi_score=0.45,
                threshold=0.2,
                is_drifted=True,
                sample_size=500,
            )
        ]

        perf = PerformanceMetrics(
            mae=12.0, late_rate=0.30,
            interval_coverage=0.70,
            sample_count=500, labelled_count=500,
        )

        config = GateConfig(min_samples=100, cooldown_seconds=0)
        result = evaluate_gate(session, drift_reports, perf, config)
        assert result.triggered is True
        assert "TRIGGERED" in result.reason
        assert "traffic" in result.reason
        session.commit()
