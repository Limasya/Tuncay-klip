"""
Platform Engineering API router (IP_PART6).

Feature flag değerlendirme/yönetimi, API key yönetimi ve A/B test yardımcılarını
HTTP üzerinden sunar. Yönetim uçları `feature-flags` scope'u ile korunur.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from platform_eng.auth import Principal, Scope, get_current_principal, require_scope
from platform_eng.auth.jwt_auth import default_api_key_store
from platform_eng.flags import FlagRule, default_client
from platform_eng.experiments import assign_variant, evaluate_ab, required_sample_size

router = APIRouter(prefix="/api/v1/platform", tags=["platform"])


# --- Feature Flags ----------------------------------------------------------
class FlagEvalRequest(BaseModel):
    key: str
    context: dict[str, Any] = Field(default_factory=dict)
    default: bool = False


class FlagEvalResponse(BaseModel):
    key: str
    enabled: bool


@router.post("/flags/evaluate", response_model=FlagEvalResponse)
async def evaluate_flag(req: FlagEvalRequest) -> FlagEvalResponse:
    """Bir feature flag'i verilen context için değerlendirir (kimlik gerekmez)."""
    enabled = default_client.get_boolean_value(req.key, req.default, req.context)
    return FlagEvalResponse(key=req.key, enabled=enabled)


@router.get("/flags")
async def list_flags(
    _principal: Principal = Depends(require_scope(Scope.FEATURE_FLAGS)),
) -> dict[str, Any]:
    """Tüm flag tanımlarını listeler (admin — feature-flags scope)."""
    return {
        key: {
            "enabled": rule.enabled,
            "type": rule.flag_type.value,
            "rollout_percentage": rule.rollout_percentage,
        }
        for key, rule in default_client.all_flags().items()
    }


class FlagUpsertRequest(BaseModel):
    enabled: bool = False
    type: str = "release"
    rollout_percentage: int = 100
    enabled_plans: Optional[list[str]] = None
    enabled_regions: Optional[list[str]] = None
    enabled_targets: list[str] = Field(default_factory=list)
    disabled_targets: list[str] = Field(default_factory=list)


@router.put("/flags/{key}")
async def upsert_flag(
    key: str,
    req: FlagUpsertRequest,
    _principal: Principal = Depends(require_scope(Scope.FEATURE_FLAGS)),
) -> dict[str, str]:
    """Bir flag'i oluşturur/günceller (admin — feature-flags scope)."""
    rule = FlagRule.from_dict(key, req.model_dump())
    default_client.set_flag(rule)
    return {"status": "ok", "key": key}


# --- API Keys ---------------------------------------------------------------
class ApiKeyCreateRequest(BaseModel):
    client_id: str
    scopes: list[str] = Field(default_factory=list)
    ttl_days: int = 90


@router.post("/api-keys")
async def create_api_key(
    req: ApiKeyCreateRequest,
    _principal: Principal = Depends(require_scope(Scope.BILLING_MANAGE)),
) -> dict[str, Any]:
    """
    Yeni API anahtarı üretir. Plaintext anahtar YALNIZCA burada döner (33.6);
    tekrar gösterilemez.
    """
    plaintext, record = default_api_key_store.create(
        req.client_id, scopes=req.scopes, ttl_days=req.ttl_days
    )
    return {
        "api_key": plaintext,  # bir kez gösterilir!
        "client_id": record.client_id,
        "expires_at": record.expires_at.isoformat(),
        "scopes": sorted(record.scopes),
    }


@router.delete("/api-keys/{key_hash}")
async def revoke_api_key(
    key_hash: str,
    _principal: Principal = Depends(require_scope(Scope.BILLING_MANAGE)),
) -> dict[str, str]:
    """Bir API anahtarını iptal eder."""
    if not default_api_key_store.revoke(key_hash):
        raise HTTPException(status_code=404, detail="key not found")
    return {"status": "revoked"}


# --- A/B Testing ------------------------------------------------------------
class AssignRequest(BaseModel):
    experiment: str
    unit_id: str
    weights: dict[str, int]


@router.post("/experiments/assign")
async def assign(req: AssignRequest) -> dict[str, str]:
    """Deterministik varyant ataması (37.5)."""
    variant = assign_variant(req.experiment, req.unit_id, req.weights)
    return {"experiment": req.experiment, "unit_id": req.unit_id, "variant": variant}


class EvaluateRequest(BaseModel):
    conv_a: int
    n_a: int
    conv_b: int
    n_b: int
    alpha: float = 0.05


@router.post("/experiments/evaluate")
async def evaluate(
    req: EvaluateRequest,
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
) -> dict[str, Any]:
    """İki-oranlı z-testi ile A/B sonucu (37.6)."""
    try:
        result = evaluate_ab(req.conv_a, req.n_a, req.conv_b, req.n_b, req.alpha)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "rate_a": result.rate_a,
        "rate_b": result.rate_b,
        "lift": result.lift,
        "z_score": result.z_score,
        "p_value": result.p_value,
        "significant": result.significant,
        "winner": result.winner,
    }


@router.get("/experiments/sample-size")
async def sample_size(
    baseline_rate: float,
    min_detectable_effect: float,
    alpha: float = 0.05,
    power: float = 0.8,
) -> dict[str, Any]:
    """Kol başına gereken örneklem büyüklüğü (37.4)."""
    try:
        n = required_sample_size(baseline_rate, min_detectable_effect, alpha, power)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"required_per_arm": n}


# --- Whoami (auth doğrulama) ------------------------------------------------
@router.get("/whoami")
async def whoami(principal: Principal = Depends(get_current_principal)) -> dict[str, Any]:
    """Kimliği doğrulanmış çağıranın rolleri ve scope'larını döndürür."""
    return {
        "subject": principal.subject,
        "auth_type": principal.auth_type,
        "roles": list(principal.roles),
        "scopes": sorted(principal.scopes),
    }
