"""
platform_eng.auth testleri (IP_PART6 Bölüm 33).

Kapsam:
  - RBAC rol/scope matrisi + has_scope
  - API key üretimi, timing-safe doğrulama, rotasyon, expire/revoke
  - Principal çözümleme (JWT + API key önceliği)
"""
import hashlib
from datetime import timedelta

import pytest
from fastapi import HTTPException
from jose import jwt

from config import get_settings
from platform_eng.auth import (
    Principal,
    Role,
    Scope,
    generate_api_key,
    verify_api_key,
    has_scope,
    scopes_for_roles,
)
from platform_eng.auth.api_keys import ApiKey, ApiKeyStore, _now, MAX_ACTIVE_KEYS_PER_CLIENT
from platform_eng.auth import jwt_auth


# ── RBAC ──────────────────────────────────────────────────────────────
def test_scopes_for_roles_admin_has_feature_flags():
    scopes = scopes_for_roles([Role.ADMIN])
    assert Scope.FEATURE_FLAGS.value in scopes
    assert Scope.BILLING_MANAGE.value in scopes


def test_scopes_for_roles_creator_cannot_delete():
    scopes = scopes_for_roles(["creator"])
    assert Scope.CLIPS_WRITE.value in scopes
    assert Scope.CLIPS_DELETE.value not in scopes


def test_scopes_for_roles_ignores_unknown_role():
    assert scopes_for_roles(["nope"]) == set()


def test_has_scope_accepts_enum_and_str():
    granted = {Scope.CLIPS_READ.value}
    assert has_scope(granted, Scope.CLIPS_READ)
    assert has_scope(granted, "clips:read")
    assert not has_scope(granted, Scope.CLIPS_DELETE)


# ── API keys ──────────────────────────────────────────────────────────
def test_generate_and_verify_api_key():
    plaintext, digest = generate_api_key()
    assert plaintext.startswith("ip_")
    assert digest == hashlib.sha256(plaintext.encode()).hexdigest()
    assert verify_api_key(plaintext, digest)
    assert not verify_api_key("ip_wrong", digest)


def test_store_create_and_authenticate():
    store = ApiKeyStore()
    plaintext, record = store.create("client-1", scopes=["clips:read"])
    authed = store.authenticate(plaintext)
    assert authed is not None
    assert authed.client_id == "client-1"
    assert authed.last_used_at is not None
    assert store.authenticate("ip_bogus") is None


def test_store_revoke_blocks_auth():
    store = ApiKeyStore()
    plaintext, record = store.create("client-2")
    assert store.revoke(record.key_hash) is True
    assert store.authenticate(plaintext) is None
    assert store.revoke("missing-hash") is False


def test_rotation_revokes_oldest_over_limit():
    store = ApiKeyStore()
    for _ in range(MAX_ACTIVE_KEYS_PER_CLIENT + 1):
        store.create("client-3")
    active = store.active_for_client("client-3")
    assert len(active) == MAX_ACTIVE_KEYS_PER_CLIENT


def test_expired_key_not_active_and_purged():
    store = ApiKeyStore()
    plaintext, record = store.create("client-4", ttl_days=90)
    # süreyi geçmişe çek
    record.expires_at = _now() - timedelta(days=1)
    assert not record.is_active()
    assert store.authenticate(plaintext) is None
    assert store.purge_expired() == 1


def test_needs_rotation_warning():
    record = ApiKey(key_hash="h", client_id="c")
    record.expires_at = _now() + timedelta(days=10)  # < 15 gün
    assert record.needs_rotation_warning()
    record.expires_at = _now() + timedelta(days=40)
    assert not record.needs_rotation_warning()


# ── Principal çözümleme ───────────────────────────────────────────────
def _make_jwt(claims: dict) -> str:
    s = get_settings()
    return jwt.encode(claims, s.secret_key, algorithm=s.algorithm)


def test_resolve_principal_via_jwt_expands_roles():
    token = _make_jwt({"sub": "user-1", "roles": ["admin"]})
    principal = jwt_auth.resolve_principal(f"Bearer {token}", None)
    assert principal.auth_type == "jwt"
    assert principal.subject == "user-1"
    assert Scope.FEATURE_FLAGS.value in principal.scopes


def test_resolve_principal_via_api_key():
    store = jwt_auth.default_api_key_store
    plaintext, record = store.create("svc-1", scopes=["clips:read"])
    principal = jwt_auth.resolve_principal(None, plaintext)
    assert principal.auth_type == "api_key"
    assert principal.subject == "svc-1"
    assert "clips:read" in principal.scopes


def test_resolve_principal_no_credentials_raises_401():
    with pytest.raises(HTTPException) as exc:
        jwt_auth.resolve_principal(None, None)
    assert exc.value.status_code == 401


def test_resolve_principal_bad_scheme_raises_401():
    with pytest.raises(HTTPException) as exc:
        jwt_auth.resolve_principal("Basic abc", None)
    assert exc.value.status_code == 401


def test_resolve_principal_invalid_token_raises_401():
    with pytest.raises(HTTPException) as exc:
        jwt_auth.resolve_principal("Bearer not-a-jwt", None)
    assert exc.value.status_code == 401
