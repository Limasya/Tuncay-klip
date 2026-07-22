"""
JWT & Principal doğrulama (IP_PART6 Bölüm 33.2-33.3).

Bu modül iki kimlik türünü destekler:
  1. Bearer JWT  (insan kullanıcılar / dashboard)  — Authorization: Bearer <jwt>
  2. API Key     (makine istemciler)               — X-API-Key: ip_...

Mevcut `config.get_settings()` (secret_key, algorithm) ve python-jose kullanılır;
böylece repodaki `utils/auth.py` ile uyumludur. Defense-in-depth: gateway JWT'yi
doğrulasa bile servis içinde tekrar doğrulanır.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Header, HTTPException

from platform_eng.auth.api_keys import ApiKeyStore
from platform_eng.auth.rbac import scopes_for_roles

logger = logging.getLogger("jwt_auth")

# Uygulama genelinde paylaşılan varsayılan API key deposu.
# (Production'da DI ile DB destekli bir store enjekte edilebilir.)
default_api_key_store = ApiKeyStore()


def bootstrap_admin_api_key() -> Optional[str]:
    """
    ADMIN_API_KEY env var'ı set edilmişse, deposu boşsa otomatik kaydeder.

    Bu fonksiyon main.py lifespan startup'ta çağrılır.
    Eğer env var'daki key zaten kayıtlıysa (restart) tekrar eklemez.

    Returns:
        Kaydedilen plaintext key ya da None (env var yoksa / zaten kayıtlıysa).
    """
    admin_key = os.environ.get("ADMIN_API_KEY", "").strip()
    if not admin_key:
        logger.info("ADMIN_API_KEY env var not set — skipping bootstrap")
        return None

    # Check if this exact key is already registered (idempotent on restart)
    existing = default_api_key_store.authenticate(admin_key)
    if existing is not None:
        logger.info("ADMIN_API_KEY already registered (client_id=%s)", existing.client_id)
        return None

    # Register with full admin scopes
    from platform_eng.auth.rbac import Role, ROLE_SCOPES
    admin_scopes = [s.value for s in ROLE_SCOPES[Role.ADMIN]]

    import hashlib
    digest = hashlib.sha256(admin_key.encode()).hexdigest()

    from platform_eng.auth.api_keys import ApiKey, _now, DEFAULT_TTL_DAYS
    from datetime import timedelta
    record = ApiKey(
        key_hash=digest,
        client_id="admin-bootstrap",
        scopes=frozenset(admin_scopes),
        expires_at=_now() + timedelta(days=DEFAULT_TTL_DAYS),
    )
    default_api_key_store._keys[digest] = record

    logger.warning(
        "ADMIN_API_KEY bootstrapped — client_id=admin-bootstrap scopes=admin "
        "(key prefix: %s...)",
        admin_key[:8],
    )
    return admin_key


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
