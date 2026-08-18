"""
Saga Orchestrator integration tests.

Tests the full distributed transaction lifecycle using in-process
service adapters (no module reloading, no network).
"""

import pytest
from fastapi.testclient import TestClient

from core.database import Base, create_db_engine, create_session_factory, init_tables
from services.inventory.app import app as inventory_app
from services.orchestrator.saga_state_machine import SagaOrchestrator, SagaState
from services.payment.app import app as payment_app

# ── Service Adapters ─────────────────────────────────────────────────────────


class PaymentAdapter:
    def __init__(self, client: TestClient):
        self.client = client

    def authorize(self, order_id: str, amount: float, idem_key: str) -> dict:
        resp = self.client.post("/payments/authorize", json={
            "order_id": order_id, "amount": amount, "idempotency_key": idem_key,
        })
        resp.raise_for_status()
        return resp.json()

    def refund(self, order_id: str, payment_id: str, idem_key: str) -> dict:
        resp = self.client.post("/payments/refund", json={
            "order_id": order_id, "payment_id": payment_id, "idempotency_key": idem_key,
        })
        resp.raise_for_status()
        return resp.json()


class InventoryAdapter:
    def __init__(self, client: TestClient):
        self.client = client

    def reserve(self, order_id: str, items: list[str], idem_key: str) -> dict:
        resp = self.client.post("/inventory/reserve", json={
            "order_id": order_id, "items": items, "idempotency_key": idem_key,
        })
        resp.raise_for_status()
        return resp.json()

    def release(self, order_id: str, reservation_id: str, idem_key: str) -> dict:
        resp = self.client.post("/inventory/release", json={
            "order_id": order_id, "reservation_id": reservation_id, "idempotency_key": idem_key,
        })
        resp.raise_for_status()
        return resp.json()


class FailingInventoryAdapter:
    def reserve(self, order_id: str, items: list[str], idem_key: str) -> dict:
        return {
            "reservation_id": "RSV-NONE", "order_id": order_id,
            "status": "OUT_OF_STOCK", "items": items,
            "idempotency_key": idem_key, "message": "Out of stock (injected)",
        }

    def release(self, order_id: str, reservation_id: str, idem_key: str) -> dict:
        return {"status": "RELEASED"}


class FailingPaymentAdapter:
    def authorize(self, order_id: str, amount: float, idem_key: str) -> dict:
        return {
            "payment_id": "PAY-NONE", "order_id": order_id, "amount": amount,
            "status": "DECLINED", "idempotency_key": idem_key,
            "message": "Card declined (injected)",
        }

    def refund(self, order_id: str, payment_id: str, idem_key: str) -> dict:
        return {"payment_id": "REF-NONE", "status": "REFUNDED"}


class MockETAService:
    def predict(self, order_data: dict) -> dict:
        return {"eta_minutes": 28.5, "lower_bound": 24.0, "upper_bound": 33.0, "degraded": False}


class FailingETAService:
    def predict(self, order_data: dict) -> dict:
        raise ConnectionError("ETA service unreachable")


# ── Fixtures ─────────────────────────────────────────────────────────────────

# Use a single in-memory SQLite for the saga DB — isolated per test via unique order IDs
_saga_engine = create_db_engine("sqlite:///:memory:")
init_tables(_saga_engine, Base)
_saga_sf = create_session_factory(_saga_engine)

_payment_client = TestClient(payment_app)
_inventory_client = TestClient(inventory_app)


@pytest.fixture
def saga_sf():
    return _saga_sf


@pytest.fixture
def pay_adapter():
    return PaymentAdapter(_payment_client)


@pytest.fixture
def inv_adapter():
    return InventoryAdapter(_inventory_client)


# ── Tests ────────────────────────────────────────────────────────────────────


def test_happy_path_order_confirmed(saga_sf, pay_adapter, inv_adapter):
    orch = SagaOrchestrator(
        session_factory=saga_sf,
        payment_service=pay_adapter,
        inventory_service=inv_adapter,
        eta_service=MockETAService(),
    )
    result = orch.start_saga(order_id="ORD-SAGA-HAPPY-001", items=["ITEM-1", "ITEM-2"], total_amount=450.0)

    assert result["state"] == SagaState.CONFIRMED.value
    assert result["payment_id"] is not None
    assert result["reservation_id"] is not None
    assert result["eta_minutes"] == 28.5
    assert result["degraded"] is False
    assert result["error_reason"] is None

    steps = orch.get_saga_steps(result["saga_id"])
    step_names = [s["step"] for s in steps]
    assert "saga_started" in step_names
    assert "payment_authorized" in step_names
    assert "inventory_reserved" in step_names
    assert "eta_received_confirmed" in step_names


def test_payment_declined_cancels_immediately(saga_sf):
    orch = SagaOrchestrator(
        session_factory=saga_sf,
        payment_service=FailingPaymentAdapter(),
        inventory_service=FailingInventoryAdapter(),
        eta_service=MockETAService(),
    )
    result = orch.start_saga(order_id="ORD-SAGA-PAYFAIL-001", items=["ITEM-1"], total_amount=100.0)

    assert result["state"] == SagaState.CANCELLED.value
    assert result["payment_id"] is None
    assert result["reservation_id"] is None
    assert result["refund_id"] is None


def test_inventory_failure_triggers_compensating_refund(saga_sf, pay_adapter):
    orch = SagaOrchestrator(
        session_factory=saga_sf,
        payment_service=pay_adapter,
        inventory_service=FailingInventoryAdapter(),
        eta_service=MockETAService(),
    )
    result = orch.start_saga(order_id="ORD-SAGA-INVFAIL-001", items=["ITEM-1"], total_amount=300.0)

    assert result["state"] == SagaState.CANCELLED.value
    assert result["payment_id"] is not None  # Payment WAS authorized
    assert result["refund_id"] is not None  # Compensating refund issued

    steps = orch.get_saga_steps(result["saga_id"])
    step_types = [s["type"] for s in steps]
    assert "COMPENSATE" in step_types


def test_eta_failure_degrades_gracefully(saga_sf, pay_adapter, inv_adapter):
    orch = SagaOrchestrator(
        session_factory=saga_sf,
        payment_service=pay_adapter,
        inventory_service=inv_adapter,
        eta_service=FailingETAService(),
    )
    result = orch.start_saga(order_id="ORD-SAGA-ETAFAIL-001", items=["ITEM-1", "ITEM-3"], total_amount=200.0)

    assert result["state"] == SagaState.CONFIRMED_DEGRADED.value
    assert result["payment_id"] is not None
    assert result["reservation_id"] is not None
    assert result["degraded"] is True
    assert result["eta_minutes"] is not None
    assert result["refund_id"] is None  # No refund — order went through


def test_no_eta_service_uses_fallback(saga_sf, pay_adapter, inv_adapter):
    orch = SagaOrchestrator(
        session_factory=saga_sf,
        payment_service=pay_adapter,
        inventory_service=inv_adapter,
        eta_service=None,
    )
    result = orch.start_saga(order_id="ORD-SAGA-NOETA-001", items=["ITEM-5"], total_amount=150.0)

    assert result["state"] == SagaState.CONFIRMED_DEGRADED.value
    assert result["degraded"] is True
    assert result["eta_minutes"] == 32.0


def test_saga_status_lookup(saga_sf, pay_adapter, inv_adapter):
    orch = SagaOrchestrator(
        session_factory=saga_sf,
        payment_service=pay_adapter,
        inventory_service=inv_adapter,
        eta_service=MockETAService(),
    )
    orch.start_saga(order_id="ORD-SAGA-LOOKUP-001", items=["ITEM-1"], total_amount=99.0)
    status = orch.get_saga_status("ORD-SAGA-LOOKUP-001")

    assert status is not None
    assert status["order_id"] == "ORD-SAGA-LOOKUP-001"
    assert status["state"] in {SagaState.CONFIRMED.value, SagaState.CONFIRMED_DEGRADED.value}
