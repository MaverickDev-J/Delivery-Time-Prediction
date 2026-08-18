"""
Notifier Service — consumes order events and logs notifications.

Subscribes to Redis Streams:
  - order.confirmed
  - order.cancelled

Idempotent: tracks processed event_ids to prevent duplicate notifications.
In a real system this would send push notifications, emails, SMS.
Here it logs to demonstrate the consumer group pattern.
"""

from core.logging import setup_logger

logger = setup_logger("notifier-service", service_name="notifier")


class NotifierService:
    """Idempotent notification handler for order lifecycle events."""

    def __init__(self):
        self._processed_events: set[str] = set()
        self._notifications: list[dict] = []

    def handle_event(self, event_type: str, event_id: str, payload: dict) -> bool:
        """Process an order event. Returns True if notification was sent (not duplicate)."""

        # Idempotency check
        if event_id in self._processed_events:
            logger.info(f"Skipping duplicate notification for event {event_id}")
            return False

        order_id = payload.get("order_id", "unknown")

        if event_type == "order.confirmed":
            notification = {
                "event_id": event_id,
                "type": "ORDER_CONFIRMED",
                "order_id": order_id,
                "message": f"Your order {order_id} has been confirmed! Estimated delivery: {payload.get('eta_minutes', 'N/A')} minutes.",
                "channel": "push_notification",
            }
        elif event_type == "order.cancelled":
            notification = {
                "event_id": event_id,
                "type": "ORDER_CANCELLED",
                "order_id": order_id,
                "message": f"Your order {order_id} has been cancelled. Reason: {payload.get('reason', 'N/A')}. Refund will be processed.",
                "channel": "push_notification",
            }
        else:
            logger.warning(f"Unknown event type: {event_type}")
            return False

        self._processed_events.add(event_id)
        self._notifications.append(notification)
        logger.info(f"Notification sent: [{notification['type']}] {notification['message']}")
        return True

    @property
    def notifications(self) -> list[dict]:
        """Return all sent notifications — useful for testing."""
        return list(self._notifications)

    @property
    def processed_count(self) -> int:
        return len(self._processed_events)

    def clear(self):
        """Reset state — useful in tests."""
        self._processed_events.clear()
        self._notifications.clear()


# Standalone FastAPI service
from fastapi import FastAPI

from core.metrics import add_metrics_middleware, expose_metrics

service = NotifierService()

app = FastAPI(title="DeliverIQ Notifier Service", version="1.0.0")
add_metrics_middleware(app, service_name="notifier")
expose_metrics(app)


@app.get("/health")
def health():
    return {"status": "UP", "service": "notifier", "processed_events": service.processed_count}


@app.get("/notifications")
def get_notifications():
    return {"notifications": service.notifications}

