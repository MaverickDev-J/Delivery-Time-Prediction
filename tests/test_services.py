"""
Unit tests for Order, Payment, and Inventory microservices.

Uses the already-imported app modules without reloading.
Tests share the module-level databases which is fine since we use
unique idempotency keys per test.
"""

import pytest
from fastapi.testclient import TestClient

from services.inventory.app import app as inventory_app
from services.order.app import app as order_app
from services.payment.app import app as payment_app


@pytest.fixture(scope="module")
def order_client():
    with TestClient(order_app) as c:
        yield c


@pytest.fixture(scope="module")
def payment_client_svc():
    with TestClient(payment_app) as c:
        yield c


@pytest.fixture(scope="module")
def inventory_client_svc():
    with TestClient(inventory_app) as c:
        yield c


# ── Order Service Tests ─────────────────────────────────────────────────────


def test_order_create_returns_202(order_client):
    resp = order_client.post("/orders", json={
        "customer_id": "CUST-001",
        "restaurant_id": "REST-001",
        "items": ["ITEM-1", "ITEM-2"],
        "total_amount": 350.0,
    }, headers={"Idempotency-Key": "test-svc-idem-order-001"})

    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "CREATED"
    assert data["order_id"].startswith("ORD-")


def test_order_idempotent_replay(order_client):
    payload = {
        "customer_id": "CUST-002",
        "restaurant_id": "REST-002",
        "items": ["ITEM-3"],
        "total_amount": 200.0,
    }
    headers = {"Idempotency-Key": "test-svc-idem-order-002"}

    resp1 = order_client.post("/orders", json=payload, headers=headers)
    resp2 = order_client.post("/orders", json=payload, headers=headers)

    assert resp1.json()["order_id"] == resp2.json()["order_id"]


def test_order_get_by_id(order_client):
    resp = order_client.post("/orders", json={
        "customer_id": "CUST-003",
        "restaurant_id": "REST-003",
        "items": ["ITEM-5"],
        "total_amount": 100.0,
    }, headers={"Idempotency-Key": "test-svc-idem-order-003"})

    order_id = resp.json()["order_id"]
    get_resp = order_client.get(f"/orders/{order_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["order_id"] == order_id


def test_order_not_found(order_client):
    resp = order_client.get("/orders/ORD-NONEXISTENT")
    assert resp.status_code == 404


# ── Payment Service Tests ───────────────────────────────────────────────────


def test_payment_authorize_success(payment_client_svc):
    resp = payment_client_svc.post("/payments/authorize", json={
        "order_id": "ORD-PAY-001",
        "amount": 250.0,
        "idempotency_key": "test-svc-idem-pay-001",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "AUTHORIZED"
    assert data["payment_id"].startswith("PAY-")


def test_payment_idempotent_authorize(payment_client_svc):
    payload = {
        "order_id": "ORD-PAY-002",
        "amount": 150.0,
        "idempotency_key": "test-svc-idem-pay-002",
    }

    resp1 = payment_client_svc.post("/payments/authorize", json=payload)
    resp2 = payment_client_svc.post("/payments/authorize", json=payload)

    assert resp1.json()["payment_id"] == resp2.json()["payment_id"]


def test_payment_refund(payment_client_svc):
    auth_resp = payment_client_svc.post("/payments/authorize", json={
        "order_id": "ORD-PAY-003",
        "amount": 500.0,
        "idempotency_key": "test-svc-idem-pay-003",
    })
    payment_id = auth_resp.json()["payment_id"]

    refund_resp = payment_client_svc.post("/payments/refund", json={
        "order_id": "ORD-PAY-003",
        "payment_id": payment_id,
        "idempotency_key": "test-svc-idem-ref-003",
    })

    assert refund_resp.status_code == 200
    data = refund_resp.json()
    assert data["status"] == "REFUNDED"
    assert data["payment_id"].startswith("REF-")


# ── Inventory Service Tests ─────────────────────────────────────────────────


def test_inventory_reserve_success(inventory_client_svc):
    resp = inventory_client_svc.post("/inventory/reserve", json={
        "order_id": "ORD-INV-001",
        "items": ["ITEM-1", "ITEM-2"],
        "idempotency_key": "test-svc-idem-inv-001",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "RESERVED"
    assert data["reservation_id"].startswith("RSV-")


def test_inventory_reserve_out_of_stock(inventory_client_svc):
    resp = inventory_client_svc.post("/inventory/reserve", json={
        "order_id": "ORD-INV-OOS",
        "items": ["ITEM-NONEXISTENT"],
        "idempotency_key": "test-svc-idem-inv-oos",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "OUT_OF_STOCK"


def test_inventory_release(inventory_client_svc):
    reserve_resp = inventory_client_svc.post("/inventory/reserve", json={
        "order_id": "ORD-INV-REL",
        "items": ["ITEM-3"],
        "idempotency_key": "test-svc-idem-inv-rel-1",
    })
    reservation_id = reserve_resp.json()["reservation_id"]

    release_resp = inventory_client_svc.post("/inventory/release", json={
        "order_id": "ORD-INV-REL",
        "reservation_id": reservation_id,
        "idempotency_key": "test-svc-idem-inv-rel-2",
    })

    assert release_resp.status_code == 200
    assert release_resp.json()["status"] == "RELEASED"


def test_inventory_idempotent_reserve(inventory_client_svc):
    payload = {
        "order_id": "ORD-INV-IDEM",
        "items": ["ITEM-4"],
        "idempotency_key": "test-svc-idem-inv-idem",
    }

    resp1 = inventory_client_svc.post("/inventory/reserve", json=payload)
    resp2 = inventory_client_svc.post("/inventory/reserve", json=payload)

    assert resp1.json()["reservation_id"] == resp2.json()["reservation_id"]
