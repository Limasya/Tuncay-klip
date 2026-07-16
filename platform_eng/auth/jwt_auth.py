"""
JWT & Principal doğrulama (IP_PART6 Bölüm 33.2-33.3).

Bu modül iki kimlik türünü destekler:
  1. Bearer JWT  (insan kullanıcılar / dashboard)  — Authorization: Bearer <jwt>
  2. API Key     (makine istemciler)               — X-API-Key: ip_...

Mevcut `config.get_settings()` (secret_key, algorithm) ve python-jose kullanılır;
böylece repodaki `utils/auth.py` ile uyumludur. Defense-in-depth: gateway JWT'yi
doğrulasa bile servis içinde tekrar doğrulanır.
"""
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Header, HTTPException

from platform_eng.auth.api_keys import ApiKeyStore
from platform_eng.auth.rbac import scopes_for_roles


# Uygulama genelinde paylaşılan varsayılan API key deposu.
# (Production'da DI ile DB destekli bir store enjekte edilebilir.)
default_api_key_store = ApiKeyStore()


@dataclass
class Principal:
    """Kimliği doğrulanmış çağıran (insan ya da servis)."""

    subject: str
    roles: tuple[str, ...] = ()
    scopes: frozenset[str] = field(default_factory=frozenset)
    auth_type: str = "jwt"  # "jwt" | "api_key"
    claims: dict = field(default_factory=dict)


def decode_token(token: str) -> Optional[dict]:
    """
    JWT'yi doğrular ve payload döndürür. Geçersizse None.

    İmza + exp doğrulaması python-jose tarafından yapılır.
    """
    from jose import JWTError, jwt
    from config import get_settings

    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None


def principal_from_claims(claims: dict) -> Principal:
    """JWT payload'ından bir Principal üretir; roller → scope'lar genişletilir."""
    roles = claims.get("roles") or ([claims["role"]] if claims.get("role") else [])
    roles = tuple(str(r) for r in roles)

    # scope'lar: açık `scope`/`scopes` claim'i + rollerden türetilenler
    explicit: set[str] = set()
    raw_scope = claims.get("scope")
    if isinstance(raw_scope, str):
        explicit.update(raw_scope.split())
    elif isinstance(raw_scope, (list, tuple)):
        explicit.update(str(s) for s in raw_scope)
    explicit.update(str(s) for s in (claims.get("scopes") or []))

    scopes = explicit | scopes_for_roles(roles)
    return Principal(
        subject=str(claims.get("sub", "")),
        roles=roles,
        scopes=frozenset(scopes),
        auth_type="jwt",
        claims=claims,
    )


def resolve_principal(
    authorization: Optional[str],
    x_api_key: Optional[str],
) -> Principal:
    """
    Header değerlerinden Principal çözümleyen saf mantık (test edilebilir).

    Öncelik: API key > Bearer JWT. İkisi de yoksa 401.
    """
    if x_api_key:
        record = default_api_key_store.authenticate(x_api_key)
        if record is None:
            raise HTTPException(status_code=401, detail="invalid api key")
        return Principal(
            subject=record.client_id,
            roles=("service",),
            scopes=frozenset(record.scopes),
            auth_type="api_key",
        )

    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="invalid authorization header")
        claims = decode_token(token)
        if claims is None:
            raise HTTPException(status_code=401, detail="invalid or expired token")
        return principal_from_claims(claims)

    raise HTTPException(status_code=401, detail="not authenticated")


def get_current_principal(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Principal:
    """FastAPI dependency: Bearer JWT veya X-API-Key header'ından Principal üretir."""
    return resolve_principal(authorization, x_api_key)
