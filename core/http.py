import asyncio
import random
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import httpx

from core.logging import get_correlation_id, setup_logger

logger = setup_logger("core.http")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenException(Exception):
    pass


class CircuitBreaker:
    """
    In-memory Circuit Breaker to prevent cascading failures.
    Transitions: CLOSED -> OPEN (after failure_threshold) -> HALF_OPEN (after recovery_timeout) -> CLOSED
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "default_circuit",
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_state_change = datetime.now(UTC)

    def _check_state(self) -> None:
        if self.state == CircuitState.OPEN:
            elapsed = (datetime.now(UTC) - self.last_state_change).total_seconds()
            if elapsed > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.last_state_change = datetime.now(UTC)
                logger.info(f"Circuit '{self.name}' transitioned from OPEN to HALF_OPEN")

    def record_success(self) -> None:
        if self.state in {CircuitState.HALF_OPEN, CircuitState.OPEN}:
            logger.info(f"Circuit '{self.name}' recovered: transitioned to CLOSED")
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_state_change = datetime.now(UTC)

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.last_state_change = datetime.now(UTC)
            logger.warning(f"Circuit '{self.name}' tripped: transitioned to OPEN ({self.failure_count} failures)")
        elif self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self.last_state_change = datetime.now(UTC)
            logger.warning(f"Circuit '{self.name}' probe failed: returned to OPEN")


class ResilientHttpClient:
    """Async HTTP client with timeout, exponential backoff with jitter, and circuit breaker."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 5.0,
        max_retries: int = 3,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
        **kwargs,
    ) -> httpx.Response:
        self.circuit_breaker._check_state()
        if self.circuit_breaker.state == CircuitState.OPEN:
            raise CircuitBreakerOpenException(
                f"Circuit '{self.circuit_breaker.name}' is OPEN. Requests blocked."
            )

        req_headers = headers.copy() if headers else {}
        correlation_id = get_correlation_id()
        if correlation_id and "X-Correlation-ID" not in req_headers:
            req_headers["X-Correlation-ID"] = correlation_id

        attempt = 0
        while attempt <= self.max_retries:
            try:
                async with httpx.AsyncClient(base_url=self.base_url or "", timeout=self.timeout) as client:
                    response = await client.request(method, url, headers=req_headers, json=json, **kwargs)
                    response.raise_for_status()
                    self.circuit_breaker.record_success()
                    return response

            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                attempt += 1
                if attempt > self.max_retries:
                    self.circuit_breaker.record_failure()
                    logger.error(f"HTTP {method} {url} failed after {attempt} attempts: {e}")
                    raise

                # Full jitter exponential backoff: sleep between 0 and 2^attempt * base_delay
                base_delay = 0.2
                sleep_time = random.uniform(0, base_delay * (2 ** attempt))
                logger.warning(f"HTTP {method} {url} failed (attempt {attempt}/{self.max_retries}). Retrying in {sleep_time:.2f}s...")
                await asyncio.sleep(sleep_time)

        raise RuntimeError("Unexpected end of retry loop")
