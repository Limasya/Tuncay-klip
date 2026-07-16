"""platform_eng.auth — kimlik doğrulama & yetkilendirme (IP_PART6 Bölüm 33)."""
from platform_eng.auth.rbac import (
    Role,
    Scope,
    ROLE_SCOPES,
    scopes_for_roles,
    has_scope,
    require_scope,
    require_any_scope,
)
from platform_eng.auth.api_keys import (
    ApiKey,
    ApiKeyStore,
    generate_api_key,
    verify_api_key,
)
from platform_eng.auth.jwt_auth import (
    decode_token,
    get_current_principal,
    Principal,
)

__all__ = [
    "Role",
    "Scope",
    "ROLE_SCOPES",
    "scopes_for_roles",
    "has_scope",
    "require_scope",
    "require_any_scope",
    "ApiKey",
    "ApiKeyStore",
    "generate_api_key",
    "verify_api_key",
    "decode_token",
    "get_current_principal",
    "Principal",
]
