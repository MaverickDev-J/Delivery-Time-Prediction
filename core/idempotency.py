"""
Idempotency Key middleware and store.

Prevents duplicate processing of the same request:
1. Client sends Idempotency-Key header.
2. Store checks if the key has been seen before.
3. If yes -> return cached response (no side effects).
4. If no -> process request, cache result, return it.

Uses an in-memory dict for offline/test and Redis for production.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

from core.logging import setup_logger

logger = setup_logger("core.idempotency")


class IdempotencyStore:
    """In-memory idempotency store — sufficient for single-process services and testing.

    In production (multi-replica), replace with Redis-backed store.
    """

    def __init__(self):
        self._store: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict | None:
        """Return cached response for the key, or None if unseen."""
        entry = self._store.get(key)
        if entry:
            logger.info(f"Idempotency cache HIT for key: {key[:16]}...")
        return entry

    def set(self, key: str, response: dict, status_code: int = 200) -> None:
        """Cache the response for a given idempotency key."""
        self._store[key] = {
            "response": response,
            "status_code": status_code,
            "cached_at": datetime.now(UTC).isoformat(),
        }
        logger.info(f"Idempotency cache SET for key: {key[:16]}...")

    def exists(self, key: str) -> bool:
        return key in self._store

    def clear(self):
        """Clear the store — useful in tests."""
        self._store.clear()


def generate_idempotency_key(*parts: str) -> str:
    """Generate a deterministic idempotency key from component parts.

    Example: generate_idempotency_key("order", order_id, "payment", "authorize")
    """
    combined = ":".join(str(p) for p in parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:32]
