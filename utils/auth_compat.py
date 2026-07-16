"""Graceful auth dependency for all API routers.

Works with or without python-jose installed:
- When platform_eng.auth is available: enforces JWT/API-key authentication
- When platform_eng.auth is unavailable: allows all requests in dev mode,
  logs a warning, and returns a dev Principal

This allows the app to start and function in development environments
where jose is not installed, while enforcing real auth in production.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)

_AUTH_AVAILABLE = False
_dev_principal = None

try:
    from platform_eng.auth import (
        Principal,
        Scope,
        get_current_principal,
        require_scope as _real_require_scope,
        require_any_scope as _real_require_any_scope,
    )
    _AUTH_AVAILABLE = True
except ImportError:
    logger.warning(
        "platform_eng.auth not available (python-jose missing). "
        "API endpoints will run in UNAUTHENTICATED dev mode. "
        "Install python-jose for production auth enforcement."
    )

    class Principal:  # type: ignore[no-redef]
        """Dev-only fallback principal when auth is unavailable."""

        def __init__(self) -> None:
            self.subject = "dev-user"
            self.roles = ("admin",)
            self.scopes = frozenset({
                "clips:read", "clips:write", "clips:delete",
                "streams:manage", "analytics:read",
                "feature-flags", "billing:manage", "internal:events",
            })
            self.auth_type = "dev"
            self.claims: dict[str, Any] = {}

    _dev_principal = Principal()

    def get_current_principal(  # type: ignore[no-redef]
        request: Request,
    ) -> Principal:
        """Dev mode: return a dev principal with all scopes."""
        return _dev_principal

    def _real_require_scope(scope: str) -> Callable:  # type: ignore[no-redef]
        pass

    def _real_require_any_scope(*scopes: str) -> Callable:  # type: ignore[no-redef]
        pass

    class Scope:  # type: ignore[no-redef]
        CLIPS_READ = "clips:read"
        CLIPS_WRITE = "clips:write"
        CLIPS_DELETE = "clips:delete"
        STREAMS_MANAGE = "streams:manage"
        ANALYTICS_READ = "analytics:read"
        FEATURE_FLAGS = "feature-flags"
        BILLING_MANAGE = "billing:manage"
        INTERNAL_EVENTS = "internal:events"


def require_scope(scope: str) -> Callable[..., Principal]:
    """FastAPI dependency factory that requires a specific scope.

    In dev mode (jose not installed), always passes.
    In production, enforces the scope via platform_eng.auth.
    """
    if _AUTH_AVAILABLE:
        return _real_require_scope(scope)

    def _dev_guard() -> Principal:
        return _dev_principal

    return _dev_guard


def require_any_scope(*scopes: str) -> Callable[..., Principal]:
    """FastAPI dependency factory that requires at least one of the scopes."""
    if _AUTH_AVAILABLE:
        return _real_require_any_scope(*scopes)

    def _dev_guard_any() -> Principal:
        return _dev_principal

    return _dev_guard_any


def is_auth_enabled() -> bool:
    """Check if real authentication is available."""
    return _AUTH_AVAILABLE
