"""Graceful auth dependency for all API routers.

Works with or without python-jose installed:
- When platform_eng.auth is available: enforces JWT/API-key authentication
- When platform_eng.auth is unavailable: allows all requests in dev mode,
  logs a warning, and returns a dev Principal

This allows the app to start and function in development environments
where jose is not installed, while enforcing real auth in production.

Set AUTH_DISABLED=1 (or true/yes) to force dev mode even when auth libs
are present (useful for tests).
"""
import logging
import os
from typing import Any, Callable, Optional

from fastapi import Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)

_AUTH_DISABLED = os.environ.get("AUTH_DISABLED", "false").lower() in ("true", "1", "yes")
_DEPLOYMENT_ENV = os.environ.get("DEPLOYMENT_ENVIRONMENT", "development").lower()
_AUTH_AVAILABLE = False
_dev_principal = None

# İkincil production guard: config.py model_validator'ı bypass edilse bile
# production'da auth_disabled etkinleştirilemez.
if _AUTH_DISABLED and _DEPLOYMENT_ENV == "production":
    logger.critical(
        "CRITICAL SECURITY: AUTH_DISABLED=1 is set in PRODUCTION environment. "
        "This is a security violation — auth bypass is NOT permitted in production. "
        "Falling back to auth enforcement. Set DEPLOYMENT_ENVIRONMENT=development to allow."
    )
    _AUTH_DISABLED = False  # Force-enable auth in production regardless of env var

_real_get_current_principal: Any = None
_real_require_scope: Any = None
_real_require_any_scope: Any = None

try:
    from platform_eng.auth import (
        Principal,
        Scope,
        get_current_principal as _real_get_current_principal,
        require_scope as _real_require_scope,
        require_any_scope as _real_require_any_scope,
    )
    if _AUTH_DISABLED:
        logger.warning(
            "AUTH_DISABLED=1 — platform_eng.auth found but auth enforcement disabled. "
            "All API endpoints will run in UNAUTHENTICATED dev mode."
        )
    else:
        _AUTH_AVAILABLE = True
except ImportError:
    logger.warning(
        "platform_eng.auth not available (python-jose missing). "
        "API endpoints will run in UNAUTHENTICATED dev mode. "
        "Install python-jose for production auth enforcement."
    )

    class Principal:  # type: ignore[no-redef]
        """Dev-only fallback principal when auth is unavailable."""

        def __init__(
            self,
            subject: str = "dev-user",
            roles: tuple[str, ...] = ("admin",),
            scopes: frozenset[str] = frozenset(),
            auth_type: str = "dev",
            claims: dict[str, Any] | None = None,
        ) -> None:
            self.subject = subject
            self.roles = roles
            self.scopes = scopes or frozenset({
                "clips:read", "clips:write", "clips:delete",
                "streams:manage", "analytics:read",
                "feature-flags", "billing:manage", "internal:events",
            })
            self.auth_type = auth_type
            self.claims = claims or {}

    class Scope:  # type: ignore[no-redef]
        CLIPS_READ = "clips:read"
        CLIPS_WRITE = "clips:write"
        CLIPS_DELETE = "clips:delete"
        STREAMS_MANAGE = "streams:manage"
        ANALYTICS_READ = "analytics:read"
        FEATURE_FLAGS = "feature-flags"
        BILLING_MANAGE = "billing:manage"
        INTERNAL_EVENTS = "internal:events"

    def _real_require_scope(scope: str) -> Callable:  # type: ignore[no-redef]
        pass

    def _real_require_any_scope(*scopes: str) -> Callable:  # type: ignore[no-redef]
        pass


_dev_principal = Principal(subject="dev-user", roles=("admin",), scopes=frozenset({
    "clips:read", "clips:write", "clips:delete",
    "streams:manage", "analytics:read",
    "feature-flags", "billing:manage", "internal:events",
}), auth_type="dev")


def _dev_get_current_principal(
    request: Request = None,
    x_api_key: Optional[str] = None,
) -> Principal:
    """Dev mode: always returns the dev principal with all scopes."""
    return _dev_principal


if _AUTH_AVAILABLE and not _AUTH_DISABLED:
    get_current_principal = _real_get_current_principal
else:
    get_current_principal = _dev_get_current_principal


def require_scope(scope: str) -> Callable:
    """FastAPI dependency factory that requires a specific scope."""
    if _AUTH_AVAILABLE and not _AUTH_DISABLED:
        return _real_require_scope(scope)

    def _dev_guard() -> Principal:
        return _dev_principal

    return _dev_guard


def require_any_scope(*scopes: str) -> Callable:
    """FastAPI dependency factory that requires at least one of the scopes."""
    if _AUTH_AVAILABLE and not _AUTH_DISABLED:
        return _real_require_any_scope(*scopes)

    def _dev_guard_any() -> Principal:
        return _dev_principal

    return _dev_guard_any


def is_auth_enabled() -> bool:
    """Check if real authentication is available."""
    return _AUTH_AVAILABLE and not _AUTH_DISABLED
