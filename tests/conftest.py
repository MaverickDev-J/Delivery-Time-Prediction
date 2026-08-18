"""
Test-global fixtures for DeliverIQ.

Automatically cleans up leftover SQLite database files before the test
session to prevent UNIQUE constraint violations from prior runs.
Provides global fixtures for ETA service testing.
"""

import glob
import os
import pytest
from fastapi.testclient import TestClient

from app import app


DB_PATTERNS = [
    "data/orders.db*",
    "data/payments.db*",
    "data/inventory.db*",
    "data/saga.db*",
]


def pytest_configure(config):
    """Clean up leftover SQLite files before test collection."""
    for pattern in DB_PATTERNS:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
            except OSError:
                pass


@pytest.fixture(scope="module")
def client():
    """FastAPI test client for ETA service."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def valid_order_payload():
    """Valid order payload conforming to OrderPredictionRequest."""
    return {
        "id": "ORD-12345",
        "rider_id": "BANGRES19DEL01",
        "age": 28.0,
        "ratings": 4.8,
        "restaurant_latitude": 12.9716,
        "restaurant_longitude": 77.5946,
        "delivery_latitude": 13.0358,
        "delivery_longitude": 77.5970,
        "order_date": "15-03-2026",
        "order_time": "19:30:00",
        "weather": "sunny",
        "traffic": "medium",
        "vehicle_condition": 2,
        "type_of_order": "meal",
        "type_of_vehicle": "motorcycle",
        "festival": "no",
        "city_type": "metropolitan",
    }
