"""
Drift Injector Tool — generates synthetic prediction log entries with
shifted feature distributions to trigger drift detection and retrain gates.

Usage:
    python -m tools.drift_injector --scenario monsoon --count 300
    python -m tools.drift_injector --scenario rush_hour --count 500
    python -m tools.drift_injector --scenario distance_shift --count 200

Scenarios:
    normal        — baseline feature distributions (no drift)
    monsoon       — weather skewed to stormy/fog (80%), distances longer
    rush_hour     — traffic skewed to jam (70%), higher order volume
    distance_shift — delivery distances 2x longer than baseline
"""

import argparse
import os
import random
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.monitoring.models import MonitoringBase, PredictionLog

# ── Reference distributions (approximate training data statistics) ───────────

REFERENCE_DISTRIBUTIONS = {
    "age": {"mean": 29.0, "std": 5.0},
    "ratings": {"mean": 4.2, "std": 0.5},
    "distance": {"mean": 8.5, "std": 4.0},
}


# ── Scenario generators ─────────────────────────────────────────────────────

def _generate_normal_features() -> dict:
    """Baseline feature distribution matching training data."""
    return {
        "age": round(random.gauss(29.0, 5.0), 1),
        "ratings": round(min(5.0, max(1.0, random.gauss(4.2, 0.5))), 1),
        "distance": round(max(1.0, random.gauss(8.5, 4.0)), 1),
        "weather": random.choices(
            ["sunny", "cloudy", "windy", "fog", "stormy"],
            weights=[40, 25, 15, 10, 10],
        )[0],
        "traffic": random.choices(
            ["low", "medium", "high", "jam"],
            weights=[20, 40, 25, 15],
        )[0],
        "city_type": random.choice(["urban", "metropolitan", "semi-urban"]),
        "type_of_order": random.choice(["snack", "meal", "drinks", "buffet"]),
        "type_of_vehicle": random.choice(["motorcycle", "scooter", "electric_scooter", "bicycle"]),
    }


def _generate_monsoon_features() -> dict:
    """Shifted: stormy/fog weather 80%, distances 1.5x longer."""
    features = _generate_normal_features()
    features["weather"] = random.choices(
        ["sunny", "cloudy", "windy", "fog", "stormy"],
        weights=[5, 5, 5, 35, 50],  # 85% fog+stormy
    )[0]
    features["distance"] = round(max(1.0, random.gauss(13.0, 5.0)), 1)  # shifted up
    return features


def _generate_rush_hour_features() -> dict:
    """Shifted: traffic jammed 70%, higher ratings (busier riders)."""
    features = _generate_normal_features()
    features["traffic"] = random.choices(
        ["low", "medium", "high", "jam"],
        weights=[5, 10, 15, 70],  # 70% jam
    )[0]
    features["ratings"] = round(min(5.0, max(1.0, random.gauss(3.5, 0.8))), 1)  # degraded
    return features


def _generate_distance_shift_features() -> dict:
    """Shifted: delivery distances 2x longer."""
    features = _generate_normal_features()
    features["distance"] = round(max(2.0, random.gauss(17.0, 6.0)), 1)  # 2x baseline
    return features


SCENARIOS = {
    "normal": _generate_normal_features,
    "monsoon": _generate_monsoon_features,
    "rush_hour": _generate_rush_hour_features,
    "distance_shift": _generate_distance_shift_features,
}


def _generate_eta(features: dict, scenario: str) -> tuple[float, float, float, float | None]:
    """Generate a realistic ETA prediction and optional actual delivery time.

    Returns (eta_minutes, lower_bound, upper_bound, actual_minutes_or_none)
    """
    base_eta = 25.0

    # Distance impact
    base_eta += features["distance"] * 1.2

    # Traffic impact
    traffic_impact = {"low": -3, "medium": 0, "high": 5, "jam": 12}
    base_eta += traffic_impact.get(features["traffic"], 0)

    # Weather impact
    weather_impact = {"sunny": 0, "cloudy": 1, "windy": 2, "fog": 5, "stormy": 8}
    base_eta += weather_impact.get(features["weather"], 0)

    # Add noise
    eta = max(10.0, base_eta + random.gauss(0, 3))
    lower = max(5.0, eta - random.uniform(4, 8))
    upper = eta + random.uniform(4, 8)

    # Generate actual delivery time
    # Under drift, actual will be WORSE than predicted (late deliveries)
    if scenario == "normal":
        actual = eta + random.gauss(0, 4)  # symmetric around prediction
    else:
        # Drifted: predictions underestimate, actuals are later
        actual = eta + random.gauss(6, 5)  # biased late

    actual = max(5.0, actual)
    return round(eta, 1), round(lower, 1), round(upper, 1), round(actual, 1)


def inject_predictions(
    db_url: str,
    scenario: str,
    count: int,
) -> int:
    """Inject synthetic prediction logs into the monitoring database.

    Returns the number of records inserted.
    """
    generator = SCENARIOS.get(scenario)
    if generator is None:
        raise ValueError(f"Unknown scenario: {scenario}. Choose from: {list(SCENARIOS.keys())}")

    engine = create_engine(db_url)
    MonitoringBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    inserted = 0
    with Session() as session:
        for _ in range(count):
            features = generator()
            eta, lower, upper, actual = _generate_eta(features, scenario)

            log = PredictionLog(
                prediction_id=f"PRED-{uuid.uuid4().hex[:12].upper()}",
                order_id=f"ORD-SIM-{uuid.uuid4().hex[:8].upper()}",
                correlation_id=f"CORR-{uuid.uuid4().hex[:8].upper()}",
                model_version="1.0.0",
                feature_schema_version="1.0.0",
                input_features=features,
                eta_minutes=eta,
                lower_bound=lower,
                upper_bound=upper,
                degraded=False,
                predicted_at=datetime.now(UTC),
                actual_minutes=actual,
                delivered_at=datetime.now(UTC),
                label_lag_seconds=random.uniform(1800, 2700),  # 30-45 min simulated lag
            )
            session.add(log)
            inserted += 1

        session.commit()

    return inserted


def main():
    parser = argparse.ArgumentParser(description="DeliverIQ Drift Injector Tool")
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        default="monsoon",
        help="Drift scenario to inject",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=300,
        help="Number of synthetic prediction logs to insert",
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("MONITORING_DB_URL", "sqlite:///data/monitoring.db"),
        help="Database URL for the monitoring service",
    )
    args = parser.parse_args()

    print(f"Injecting {args.count} predictions with scenario '{args.scenario}'...")
    inserted = inject_predictions(args.db_url, args.scenario, args.count)
    print(f"Done. Inserted {inserted} prediction log entries into {args.db_url}.")


if __name__ == "__main__":
    main()
