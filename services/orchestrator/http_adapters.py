"""
HTTP service adapters for the Saga Orchestrator.

These wrap real HTTP calls to downstream services into the same interface
the SagaOrchestrator expects (authorize, refund, reserve, release, predict).
Used in Docker Compose production mode. Tests inject mocks instead.
"""

import httpx

from core.logging import setup_logger

logger = setup_logger("http-adapters", service_name="saga-orchestrator")

DEFAULT_TIMEOUT = 10.0


class HttpPaymentService:
    """Calls Payment Service over HTTP."""

    def __init__(self, base_url: str = "http://payment-service:8002"):
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=DEFAULT_TIMEOUT)

    def authorize(self, order_id: str, amount: float, idempotency_key: str) -> dict:
        response = self.client.post(
            "/payments/authorize",
            json={"order_id": order_id, "amount": amount, "idempotency_key": idempotency_key},
        )
        if response.status_code >= 500:
            raise ConnectionError(f"Payment service error: {response.status_code}")
        if response.status_code == 422:
            raise ConnectionError(f"Payment validation error: {response.text}")
        return response.json()

    def refund(self, order_id: str, payment_id: str, idempotency_key: str) -> dict:
        response = self.client.post(
            "/payments/refund",
            json={"order_id": order_id, "payment_id": payment_id, "idempotency_key": idempotency_key},
        )
        if response.status_code >= 500:
            raise ConnectionError(f"Payment service error: {response.status_code}")
        return response.json()


class HttpInventoryService:
    """Calls Inventory Service over HTTP."""

    def __init__(self, base_url: str = "http://inventory-service:8003"):
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=DEFAULT_TIMEOUT)

    def reserve(self, order_id: str, items: list[str], idempotency_key: str) -> dict:
        response = self.client.post(
            "/inventory/reserve",
            json={"order_id": order_id, "items": items, "idempotency_key": idempotency_key},
        )
        if response.status_code >= 500:
            raise ConnectionError(f"Inventory service error: {response.status_code}")
        if response.status_code == 422:
            raise ConnectionError(f"Inventory validation error: {response.text}")
        return response.json()

    def release(self, order_id: str, reservation_id: str, idempotency_key: str) -> dict:
        response = self.client.post(
            "/inventory/release",
            json={"order_id": order_id, "reservation_id": reservation_id, "idempotency_key": idempotency_key},
        )
        if response.status_code >= 500:
            raise ConnectionError(f"Inventory service error: {response.status_code}")
        return response.json()


class HttpEtaService:
    """Calls ETA Service over HTTP."""

    def __init__(self, base_url: str = "http://eta-service:8000"):
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=DEFAULT_TIMEOUT)

    def predict(self, order_data: dict) -> dict:
        # Translate saga order_data keys → ETA service OrderPredictionRequest keys
        city_raw = order_data.get("city") or order_data.get("city_type", "metropolitan")
        city_map = {
            "Metropolitian": "metropolitan",
            "Urban": "urban",
            "Semi-Urban": "semi-urban",
            "metropolitan": "metropolitan",
            "urban": "urban",
            "semi-urban": "semi-urban",
        }

        eta_payload = {
            "id": str(order_data.get("order_id", "ORD-SAGA")),
            "rider_id": "RIDER_DEFAULT",
            "age": float(order_data.get("delivery_person_age", 28)),
            "ratings": float(order_data.get("delivery_person_ratings", 4.5)),
            "restaurant_latitude": float(order_data.get("restaurant_latitude", 12.97)),
            "restaurant_longitude": float(order_data.get("restaurant_longitude", 77.59)),
            "delivery_latitude": float(order_data.get("delivery_location_latitude", 12.93)),
            "delivery_longitude": float(order_data.get("delivery_location_longitude", 77.62)),
            "order_date": str(order_data.get("order_date", "2026-08-20")),
            "order_time": str(order_data.get("time_order_picked", "19:30:00")),
            "weather": str(order_data.get("weather_conditions", "sunny")).lower(),
            "traffic": str(order_data.get("road_traffic_density", "medium")).lower(),
            "vehicle_condition": int(order_data.get("vehicle_condition", 2)),
            "type_of_order": str(order_data.get("type_of_order", "meal")).lower(),
            "type_of_vehicle": str(order_data.get("type_of_vehicle", "motorcycle")).lower(),
            "festival": str(order_data.get("festival", "no")).lower(),
            "city_type": city_map.get(city_raw, "metropolitan"),
        }

        response = self.client.post("/predict", json=eta_payload)
        if response.status_code >= 500:
            raise ConnectionError(f"ETA service error: {response.status_code}")
        if response.status_code >= 400:
            logger.warning(f"ETA prediction failed with {response.status_code}: {response.text}")
            return {"eta_minutes": 35, "degraded": True}
        return response.json()


class HttpOrderService:
    """Calls Order Service to update status after saga completion."""

    def __init__(self, base_url: str = "http://order-service:8001"):
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=DEFAULT_TIMEOUT)

    def update_status(self, order_id: str, status: str, eta_minutes: float | None = None) -> dict:
        payload = {"status": status}
        if eta_minutes is not None:
            payload["eta_minutes"] = eta_minutes
        response = self.client.patch(f"/orders/{order_id}", json=payload)
        if response.status_code >= 500:
            raise ConnectionError(f"Order service error: {response.status_code}")
        return response.json()
