"""
LLM model defaults — litellm_config.yaml tek kaynak.

Gemini varsayılan model adı yalnızca litellm_config.yaml içinde tanımlıdır.
Kod tarafında doğrudan model string'i yazmak yerine bu modülü kullanın.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "litellm_config.yaml"
_GEMINI_FALLBACK = "gemini-2.5-flash"


@lru_cache(maxsize=1)
def _load_litellm_config() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        return {}
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _bare_gemini_model_id(provider_model: str) -> str:
    prefix = "gemini/"
    if provider_model.startswith(prefix):
        return provider_model[len(prefix):]
    return provider_model


def get_gemini_model_default() -> str:
    """litellm_config.yaml gemini.provider_model değerinden prefix'siz model ID döner."""
    config = _load_litellm_config()
    prov = config.get("tuncay_klip", {}).get("providers", {}).get("gemini", {})
    raw = prov.get("provider_model", f"gemini/{_GEMINI_FALLBACK}")
    return _bare_gemini_model_id(raw)


def resolve_gemini_model() -> str:
    """GEMINI_MODEL ortam değişkeni varsa onu, yoksa YAML varsayılanını döner."""
    return os.environ.get("GEMINI_MODEL", get_gemini_model_default())
