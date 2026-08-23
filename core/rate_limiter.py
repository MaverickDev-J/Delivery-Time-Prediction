"""
Rate Limiter — in-memory sliding-window counter.

Design:
  - Sliding window: tracks requests within a rolling time window
  - Per-user when authenticated (keyed by user_id)
  - Per-IP when anonymous (keyed by client IP)
  - Returns rate limit headers on every response:
      X-RateLimit-Limit: max requests allowed in window
      X-RateLimit-Remaining: requests left
      X-RateLimit-Reset: seconds until window resets

Interview talking points:
  - "Why sliding window over fixed window?"
    → Fixed window has a burst problem at the boundary (2x limit in 1 second at the edge).
    → Sliding window smooths this out.
  - "Why rate limit at two layers?"
    → Edge proxy: per-IP, no identity needed, stops DDoS
    → Application: per-user/tenant, needs auth context, enforces business limits
  - "Why not token bucket?"
    → Token bucket allows bursts up to bucket size. Sliding window is simpler and
      sufficient for API rate limiting. Token bucket is better for streaming/bandwidth.

Production: replace with Redis ZSET or Lua script for multi-replica consistency.
This in-memory version is correct for single-process and sufficient for demo.
"""

import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from core.logging import setup_logger

logger = setup_logger("core.rate_limiter")


class SlidingWindowRateLimiter:
    """In-memory sliding-window rate limiter.

    Tracks timestamps of requests per key. On each request:
    1. Discard timestamps older than the window
    2. If count >= limit, reject with 429
    3. Otherwise, record the timestamp and allow

    Thread-safe: single-process with GIL is sufficient.
    """

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _cleanup(self, key: str, now: float) -> None:
        """Remove timestamps outside the current window."""
        cutoff = now - self.window_seconds
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]

    def check(self, key: str) -> tuple[bool, int, int, int]:
        """Check if a request is allowed.

        Returns:
            (allowed, limit, remaining, reset_seconds)
        """
        now = time.time()
        self._cleanup(key, now)

        current_count = len(self._requests[key])
        remaining = max(0, self.max_requests - current_count)

        if current_count >= self.max_requests:
            # Calculate when the oldest request in the window expires
            oldest = self._requests[key][0] if self._requests[key] else now
            reset_at = int(oldest + self.window_seconds - now) + 1
            return False, self.max_requests, 0, reset_at

        # Allow the request
        self._requests[key].append(now)
        remaining = max(0, self.max_requests - current_count - 1)
        return True, self.max_requests, remaining, self.window_seconds


# Global rate limiter instance
_rate_limiter = SlidingWindowRateLimiter(max_requests=30, window_seconds=60)


def get_rate_limit_key(request: Request) -> str:
    """Determine the rate limit key: user_id if authenticated, else client IP."""
    # Check if auth context was already resolved
    auth = getattr(request.state, "auth", None)
    if auth and hasattr(auth, "user_id"):
        return f"user:{auth.user_id}"

    # Fall back to client IP
    client_ip = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    return f"ip:{client_ip}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces rate limiting on all requests.

    Adds rate limit headers to every response:
      X-RateLimit-Limit: 30
      X-RateLimit-Remaining: 27
      X-RateLimit-Reset: 45
    """

    def __init__(self, app, rate_limiter: SlidingWindowRateLimiter | None = None):
        super().__init__(app)
        self.limiter = rate_limiter or _rate_limiter

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks and metrics
        if request.url.path in ("/health", "/metrics", "/ready"):
            return await call_next(request)

        key = get_rate_limit_key(request)
        allowed, limit, remaining, reset = self.limiter.check(key)

        if not allowed:
            logger.warning(f"Rate limit exceeded for {key}")
            return Response(
                content=f'{{"detail":"Rate limit exceeded. Retry after {reset} seconds."}}',
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                media_type="application/json",
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset),
                    "Retry-After": str(reset),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset)
        return response
