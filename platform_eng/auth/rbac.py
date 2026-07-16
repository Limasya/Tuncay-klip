"""
RBAC — Rol tabanlı erişim kontrolü (IP_PART6 Bölüm 33.4).

Doküman 33.4'teki Role/Scope matrisinin çalışan implementasyonu.
Scope guard'lar FastAPI dependency olarak kullanılır.
"""
from enum import Enum
from typing import Any, Callable, Iterable

from fastapi import Depends, HTTPException


class Role(str, Enum):
    """Sistem rolleri (IP_PART6 33.4 matrisi)."""

    CREATOR = "creator"
    EDITOR = "editor"
    ADMIN = "admin"
    SERVICE = "service"


class Scope(str, Enum):
    """Fine-grained izinler."""

    CLIPS_READ = "clips:read"
    CLIPS_WRITE = "clips:write"
    CLIPS_DELETE = "clips:delete"
    STREAMS_MANAGE = "streams:manage"
    ANALYTICS_READ = "analytics:read"
    FEATURE_FLAGS = "feature-flags"
    BILLING_MANAGE = "billing:manage"
    INTERNAL_EVENTS = "internal:events"


# IP_PART6 33.4 — Role / Scope matrisi (dokümandaki tabloyla bire bir)
ROLE_SCOPES: dict[Role, frozenset[Scope]] = {
    Role.CREATOR: frozenset({
        Scope.CLIPS_READ,
        Scope.CLIPS_WRITE,
        Scope.STREAMS_MANAGE,
        Scope.ANALYTICS_READ,
    }),
    Role.EDITOR: frozenset({
        Scope.CLIPS_READ,
        Scope.CLIPS_WRITE,
        Scope.CLIPS_DELETE,
        Scope.ANALYTICS_READ,
    }),
    Role.ADMIN: frozenset({
        Scope.CLIPS_READ,
        Scope.CLIPS_WRITE,
        Scope.CLIPS_DELETE,
        Scope.STREAMS_MANAGE,
        Scope.ANALYTICS_READ,
        Scope.FEATURE_FLAGS,
        Scope.BILLING_MANAGE,
    }),
    Role.SERVICE: frozenset({
        Scope.CLIPS_READ,
        Scope.CLIPS_WRITE,
        Scope.INTERNAL_EVENTS,
    }),
}


def _coerce_role(role: str | Role) -> Role | None:
    if isinstance(role, Role):
        return role
    try:
        return Role(role)
    except ValueError:
        return None


def _coerce_scope(scope: str | Scope) -> str:
    return scope.value if isinstance(scope, Scope) else str(scope)


def scopes_for_roles(roles: Iterable[str | Role]) -> set[str]:
    """Verilen rollerin sağladığı tüm scope'ların birleşimini döndürür."""
    result: set[str] = set()
    for raw in roles:
        role = _coerce_role(raw)
        if role is not None:
            result.update(s.value for s in ROLE_SCOPES[role])
    return result


def has_scope(granted: Iterable[str | Scope], required: str | Scope) -> bool:
    """`granted` scope kümesi `required` scope'u içeriyor mu?"""
    required_v = _coerce_scope(required)
    return required_v in {_coerce_scope(s) for s in granted}


# ---------------------------------------------------------------------------
# FastAPI dependency fabrikaları
# ---------------------------------------------------------------------------
def require_scope(required: str | Scope) -> Callable:
    """
    Route-level scope guard (IP_PART6 33.3).

    Kullanım:
        @router.get("/clips", dependencies=[Depends(require_scope(Scope.CLIPS_READ))])
    veya principal'a ihtiyaç varsa:
        def handler(principal = Depends(require_scope("clips:read"))): ...
    """
    from platform_eng.auth.jwt_auth import get_current_principal
    required_v = _coerce_scope(required)

    def _guard(principal: Any = Depends(get_current_principal)):
        if not has_scope(principal.scopes, required_v):
            raise HTTPException(status_code=403, detail=f"missing scope: {required_v}")
        return principal

    return _guard


def require_any_scope(*required: str | Scope) -> Callable:
    """Verilen scope'lardan en az birine sahip olmayı şart koşar."""
    from platform_eng.auth.jwt_auth import get_current_principal
    needed = {_coerce_scope(s) for s in required}

    def _guard(principal: Any = Depends(get_current_principal)):
        if not (needed & set(principal.scopes)):
            raise HTTPException(
                status_code=403,
                detail=f"requires one of: {sorted(needed)}",
            )
        return principal

    return _guard
