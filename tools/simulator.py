"""
Traffic Simulator — replays order streams against the DeliverIQ system.

Simulates realistic customer traffic patterns, failure scenarios, and delayed delivery actuals.

Usage:
    python -m tools.simulator --count 50 --rate 5 --scenario normal
    python -m tools.simulator --count 100 --rate 10 --scenario monsoon
    python -m tools.simulator --count 30 --rate 2 --scenario chaos
"""

import argparse
import os
import random
import sys
import time
import uuid

import httpx

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import setup_logger
from tools.drift_injector import SCENARIOS

logger = setup_logger("traffic-simulator")


def generate_order_payload(scenario: str = "normal") -> tuple[str, list[str], float, dict]:
    """Generate a realistic order request matching the scenario."""
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"

    feature_gen = SCENARIOS.get(scenario, SCENARIOS["normal"])
    features = feature_gen()

    # Items and amount
    item_count = random.randint(1, 3)
    items = [f"ITEM-{random.randint(1, 20)}" for _ in range(item_count)]

    if scenario == "chaos" and random.random() < 0.3:
        # Trigger payment failure over amount limit
        total_amount = 15000.0
    else:
        total_amount = round(random.uniform(150.0, 1200.0), 2)

    # Order data payload for ETA inference
    order_data = {
        "delivery_person_age": int(features["age"]),
        "delivery_person_ratings": float(features["ratings"]),
        "restaurant_latitude": 12.9716 + random.uniform(-0.05, 0.05),
        "restaurant_longitude": 77.5946 + random.uniform(-0.05, 0.05),
        "delivery_location_latitude": 12.9716 + (features["distance"] * 0.009),
        "delivery_location_longitude": 77.5946 + (features["distance"] * 0.009),
        "order_date": "2026-08-18",
        "time_order_picked": "19:30:00",
        "weather_conditions": features["weather"],
        "road_traffic_density": features["traffic"],
        "vehicle_condition": 2,
        "type_of_order": features["type_of_order"],
        "type_of_vehicle": features["type_of_vehicle"],
        "city": features["city_type"],
    }

    return order_id, items, total_amount, order_data


def run_simulation(
    orchestrator_url: str,
    monitoring_url: str | None,
    count: int,
    rate: float,
    scenario: str,
):
    """Run the traffic simulation loop."""
    print("\n=======================================================")
    print("🚀 DeliverIQ Traffic Simulator")
    print(f"   Target:    {orchestrator_url}")
    print(f"   Scenario:  {scenario.upper()}")
    print(f"   Orders:    {count}")
    print(f"   Rate:      {rate} req/s")
    print("=======================================================\n")

    client = httpx.Client(timeout=15.0)

    stats = {
        "CONFIRMED": 0,
        "CONFIRMED_DEGRADED": 0,
        "CANCELLED": 0,
        "ERROR": 0,
        "latencies": [],
    }

    interval = 1.0 / rate if rate > 0 else 0.0

    for i in range(1, count + 1):
        order_id, items, total_amount, order_data = generate_order_payload(scenario)

        start_time = time.perf_counter()

        try:
            resp = client.post(
                f"{orchestrator_url}/saga/start",
                json={
                    "order_id": order_id,
                    "items": items,
                    "total_amount": total_amount,
                    "order_data": order_data,
                },
            )
            latency = (time.perf_counter() - start_time) * 1000
            stats["latencies"].append(latency)

            if resp.status_code == 200:
                result = resp.json()
                final_state = result.get("final_state", "UNKNOWN")
                if final_state in stats:
                    stats[final_state] += 1
                else:
                    stats["CONFIRMED"] += 1

                eta = result.get("eta_minutes")
                eta_str = f"{eta:.1f}m" if eta else "N/A"
                print(f"[{i:03d}/{count:03d}] {order_id} | State: {final_state:<18} | ETA: {eta_str:<6} | {latency:6.1f}ms")

                # Log actual delivery if monitoring service is configured
                if monitoring_url and final_state in ("CONFIRMED", "CONFIRMED_DEGRADED"):
                    try:
                        actual = (eta or 30.0) + (random.gauss(6, 4) if scenario != "normal" else random.gauss(0, 3))
                        actual = max(5.0, round(actual, 1))
                        client.post(
                            f"{monitoring_url}/monitoring/log-actual",
                            json={"order_id": order_id, "actual_minutes": actual},
                            timeout=2.0,
                        )
                    except Exception as err:
                        logger.debug(f"Could not log actual for {order_id}: {err}")
            else:
                stats["ERROR"] += 1
                print(f"[{i:03d}/{count:03d}] {order_id} | HTTP {resp.status_code}: {resp.text[:60]}")

        except Exception as e:
            stats["ERROR"] += 1
            print(f"[{i:03d}/{count:03d}] {order_id} | Connection failed: {e}")

        if interval > 0 and i < count:
            time.sleep(interval)

    # Print summary
    avg_lat = sum(stats["latencies"]) / len(stats["latencies"]) if stats["latencies"] else 0
    p95_lat = sorted(stats["latencies"])[int(len(stats["latencies"]) * 0.95)] if stats["latencies"] else 0

    print("\n=======================================================")
    print("📊 Simulation Results")
    print(f"   Confirmed:          {stats['CONFIRMED']}")
    print(f"   Degraded:           {stats['CONFIRMED_DEGRADED']}")
    print(f"   Cancelled:          {stats['CANCELLED']}")
    print(f"   Errors:             {stats['ERROR']}")
    print(f"   Avg Latency:        {avg_lat:.1f}ms")
    print(f"   p95 Latency:        {p95_lat:.1f}ms")
    print("=======================================================\n")


def main():
    parser = argparse.ArgumentParser(description="DeliverIQ Traffic Simulator")
    parser.add_argument("--count", type=int, default=30, help="Number of orders to place")
    parser.add_argument("--rate", type=float, default=2.0, help="Orders per second")
    parser.add_argument(
        "--scenario",
        choices=["normal", "monsoon", "rush_hour", "chaos"],
        default="normal",
        help="Traffic scenario pattern",
    )
    parser.add_argument(
        "--orchestrator-url",
        default=os.environ.get("ORCHESTRATOR_URL", "http://localhost:8004"),
        help="Saga Orchestrator URL",
    )
    parser.add_argument(
        "--monitoring-url",
        default=os.environ.get("MONITORING_URL", "http://localhost:8006"),
        help="Monitoring Service URL (optional)",
    )
    args = parser.parse_args()

    run_simulation(
        orchestrator_url=args.orchestrator_url,
        monitoring_url=args.monitoring_url,
        count=args.count,
        rate=args.rate,
        scenario=args.scenario,
    )


if __name__ == "__main__":
    main()
