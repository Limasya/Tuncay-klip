"""
Rate Limiting Middleware
────────────────────────
In-memory sliding window rate limiter for FastAPI endpoints.
Prevents abuse and protects server resources.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("rate_limiter")


class RateLimiter:
    """
    Sliding window rate limiter.

    Tracks requests per client IP and enforces a maximum number
    of requests within a rolling time window.
    """

    def __init__(
        self,
        max_requests: int = 100,
        window_seconds: int = 60,
        exclude_paths: Optional[list[str]] = None,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.exclude_paths = set(exclude_paths or ["/health", "/ready", "/api/pipeline/ws"])
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._blocked_count = 0
        self._total_count = 0

    def _get_client_key(self, request: Request) -> str:
        """Get unique client identifier."""
        # Use X-Forwarded-For if behind proxy, else direct IP
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _should_exclude(self, path: str) -> bool:
        """Check if path is excluded from rate limiting."""
        for prefix in self.exclude_paths:
            if path.startswith(prefix):
                return True
        return False

    def check_rate_limit(self, client_key: str) -> tuple[bool, dict]:
        """
        Check if a client is within rate limits.

        Returns (allowed: bool, headers: dict with rate limit info).
        """
        now = time.time()
        window_start = now - self.window_seconds

        # Clean old entries
        self._requests[client_key] = [
            t for t in self._requests[client_key] if t > window_start
        ]

        current_count = len(self._requests[client_key])
        remaining = max(0, self.max_requests - current_count)
        reset_at = int(now + self.window_seconds)

        headers = {
            "X-RateLimit-Limit": str(self.max_requests),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_at),
        }

        if current_count >= self.max_requests:
            self._blocked_count += 1
            headers["Retry-After"] = str(self.window_seconds)
            return False, headers

        # Record this request
        self._requests[client_key].append(now)
        self._total_count += 1
        headers["X-RateLimit-Remaining"] = str(remaining - 1)

        return True, headers

    def cleanup(self):
        """Remove expired entries to free memory."""
        now = time.time()
        window_start = now - self.window_seconds
        expired_keys = []
        for key, timestamps in self._requests.items():
            timestamps[:] = [t for t in timestamps if t > window_start]
            if not timestamps:
                expired_keys.append(key)
        for key in expired_keys:
            del self._requests[key]

    def get_stats(self) -> dict:
        return {
            "max_requests": self.max_requests,
            "window_seconds": self.window_seconds,
            "active_clients": len(self._requests),
            "total_requests": self._total_count,
            "blocked_requests": self._blocked_count,
        }


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that applies rate limiting to all requests."""

    def __init__(self, app, limiter: Optional[RateLimiter] = None):
        super().__init__(app)
        self.limiter = limiter or RateLimiter()

    async def dispatch(self, request: Request, call_next):
        # Skip excluded paths
        if self.limiter._should_exclude(request.url.path):
            return await call_next(request)

        client_key = self.limiter._get_client_key(request)
        allowed, headers = self.limiter.check_rate_limit(client_key)

        if not allowed:
            logger.warning(
                "Rate limit exceeded: %s (%s)",
                client_key, request.url.path,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Too many requests. Try again in {headers.get('Retry-After', 60)}s.",
                },
                headers=headers,
            )

        response = await call_next(request)

        # Add rate limit headers to response
        for key, value in headers.items():
            response.headers[key] = value

        return response


# Global singleton
_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create the global rate limiter."""
    global _limiter
    if _limiter is None:
        import os
        _limiter = RateLimiter(
            max_requests=int(os.environ.get("RATE_LIMIT_MAX", "200")),
            window_seconds=int(os.environ.get("RATE_LIMIT_WINDOW", "60")),
        )
    return _limiter
