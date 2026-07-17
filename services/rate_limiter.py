"""
Rate Limiter Middleware
──────────────────────
Token-bucket rate limiting per client IP or API key.

Features:
- Per-IP and per-API-key limits
- Configurable burst + sustained rate
- Retry-After header on 429
- Whitelist for health/docs endpoints
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class TokenBucket:
    """Simple token bucket for rate limiting."""

    def __init__(self, rate: float, capacity: int):
        self.rate = rate          # tokens per second
        self.capacity = capacity  # max burst
        self._tokens: float = capacity
        self._last_refill: float = time.time()

    def consume(self, tokens: int = 1) -> tuple[bool, float]:
        """
        Try to consume tokens.
        Returns (allowed, retry_after_seconds).
        """
        now = time.time()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

        if self._tokens >= tokens:
            self._tokens -= tokens
            return True, 0.0
        else:
            retry_after = (tokens - self._tokens) / self.rate
            return False, retry_after


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware with per-IP token buckets."""

    SKIP_PATHS = {"/health", "/ready", "/metrics", "/docs", "/openapi.json", "/redoc"}

    def __init__(self, app, requests_per_minute: int = 60, burst: int = 20):
        super().__init__(app)
        self.rpm = requests_per_minute
        self.burst = burst
        self._buckets: dict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(rate=requests_per_minute / 60.0, capacity=burst)
        )

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in self.SKIP_PATHS or path.startswith("/static"):
            return await call_next(request)

        # Identify client
        client_ip = request.client.host if request.client else "unknown"
        api_key = request.headers.get("X-API-Key", "")
        client_id = f"ip:{client_ip}" if not api_key else f"key:{api_key}"

        bucket = self._buckets[client_id]
        allowed, retry_after = bucket.consume()

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Too many requests. Retry after {retry_after:.1f}s",
                    "retry_after": round(retry_after, 1),
                },
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

        response = await call_next(request)
        # Add rate limit headers
        remaining = int(bucket._tokens)
        response.headers["X-RateLimit-Limit"] = str(self.burst)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        return response
