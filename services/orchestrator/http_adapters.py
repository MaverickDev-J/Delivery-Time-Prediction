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

    def __init__(self, base_url: str = "http://payment:8002"):
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

    def __init__(self, base_url: str = "http://inventory:8003"):
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

    def __init__(self, base_url: str = "http://eta:8000"):
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=DEFAULT_TIMEOUT)

    def predict(self, order_data: dict) -> dict:
        # Translate saga order_data keys → ETA service OrderPredictionRequest keys
        city_raw = order_data.get("city", "Metropolitian")
        city_map = {
            "Metropolitian": "metropolitan",
            "Urban": "urban",
            "Semi-Urban": "semi-urban",
            "metropolitan": "metropolitan",
            "urban": "urban",
            "semi-urban": "semi-urban",
        }

        eta_payload = {
            "id": order_data.get("order_id", "ORD-SAGA"),
            "rider_id": "RIDER_DEFAULT",
            "age": order_data.get("delivery_person_age", 28),
            "ratings": order_data.get("delivery_person_ratings", 4.5),
            "restaurant_latitude": order_data.get("restaurant_latitude", 12.97),
            "restaurant_longitude": order_data.get("restaurant_longitude", 77.59),
            "delivery_latitude": order_data.get("delivery_location_latitude", 12.93),
            "delivery_longitude": order_data.get("delivery_location_longitude", 77.62),
            "order_date": order_data.get("order_date", "18-08-2026"),
            "order_time": order_data.get("time_order_picked", "19:30:00"),
            "weather": order_data.get("weather_conditions", "sunny"),
            "traffic": order_data.get("road_traffic_density", "medium"),
            "vehicle_condition": order_data.get("vehicle_condition", 2),
            "type_of_order": order_data.get("type_of_order", "meal"),
            "type_of_vehicle": order_data.get("type_of_vehicle", "motorcycle"),
            "festival": order_data.get("festival", "no"),
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

    def __init__(self, base_url: str = "http://order:8001"):
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
