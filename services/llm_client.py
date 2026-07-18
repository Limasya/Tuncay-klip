"""
LiteLLM SDK Facade (Zero-Cost Phase — Spike)
────────────────────────────────────────────
`services/llm_engine.LLMEngine` ile aynı method imzalarını koruyan ince bir
katman. `litellm.Router` üzerinden çoklu provider fallback zinciri yönetir.

Davranış kuralları (zero-cost policy):
  - `litellm_config.yaml` içinde `enabled: true` olarak işaretlenmemiş hiçbir
    uzak provider yüklenmez; API anahtarı tek başına etkinleştirmez.
  - Ücretli/deneme sağlayıcıları hiçbir zincirde varsayılan olarak bulunmaz.
  - `template_content_fallback` her zincirin terminal adımıdır; tüm provider'lar
    başarısız olduğunda uygulama çökmez, template üretir.
  - Feature flag `llm_litellm_router` varsayılan olarak kapalıdır; kapalıyken
    çağrılar `llm_engine`'e yönlendirilir (geri uyumlu).

Kullanım:
    from services.llm_client import llm_client
    text = await llm_client.generate("title_generation", language="tr", context={...})

Yapılandırma kaynağı: litellm_config.yaml (repo root).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import yaml

from platform_eng.flags.client import is_enabled

logger = logging.getLogger("llm_client")

# ---------------------------------------------------------------------------
# LiteLLM opsiyonel import — flag kapalıyken litellm yüklü olmasa da çalışır.
# ---------------------------------------------------------------------------
try:
    import litellm  # type: ignore
    from litellm import Router  # type: ignore
    _LITELLM_AVAILABLE = True
except Exception:  # pragma: no cover — litellm yoksa facade devre dışı
    litellm = None  # type: ignore
    Router = None  # type: ignore
    _LITELLM_AVAILABLE = False

# Mevcut prompt template'leri ve emergency fallback yeniden kullanılır.
from services.llm_engine import PROMPT_TEMPLATES, LLMEngine

_legacy_engine: Optional[LLMEngine] = None
_router: Optional["Router"] = None
_router_initialized = False
_config_cache: Optional[dict[str, Any]] = None

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "litellm_config.yaml"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
def _load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """litellm_config.yaml dosyasını yükler (cache'li)."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    if not path.exists():
        logger.warning("litellm_config.yaml bulunamadı: %s", path)
        _config_cache = {}
        return _config_cache
    with open(path, "r", encoding="utf-8") as f:
        _config_cache = yaml.safe_load(f) or {}
    logger.info("LiteLLM config yüklendi: %s", path)
    return _config_cache


def _resolve_env(name: Optional[str], default: str = "") -> str:
    """Config'teki env referansını gerçek değere çevirir."""
    if not name:
        return default
    return os.environ.get(name, default)


def _build_model_list(config: dict[str, Any]) -> list[dict[str, Any]]:
    """
    `litellm.Router`'ın beklediği `model_list` formatını üretir.

    Yalnızca `enabled: true` olan provider'lar listeye eklenir. Remote provider'lar
    için `api_key` env'den çözülür; boşsa provider atlanır (zero-cost kuralı).
    """
    providers = config.get("tuncay_klip", {}).get("providers", {})
    model_list: list[dict[str, Any]] = []

    for name, prov in providers.items():
        if not prov.get("enabled", False):
            continue

        # Model adı: sabit değer veya env referansı
        model_val = prov.get("provider_model", "")
        model_env = prov.get("model_env")
        if model_env:
            model_name = _resolve_env(model_env, model_val)
        else:
            model_name = model_val

        if not model_name:
            logger.debug("Provider %s: model adı boş, atlanıyor", name)
            continue

        entry: dict[str, Any] = {
            "model_name": name,
            "litellm_params": {"model": model_name},
        }

        # API key (remote provider'lar için zorunlu)
        key_env = prov.get("api_key_env")
        if key_env:
            api_key = _resolve_env(key_env, "")
            if not api_key:
                logger.info(
                    "Provider %s: %s env boş → atlanıyor (zero-cost: "
                    "etkinleştirmek kullanıcı kararı)",
                    name, key_env,
                )
                continue
            entry["litellm_params"]["api_key"] = api_key

        # api_base (local provider'lar için)
        base_env = prov.get("api_base_env")
        default_base = prov.get("default_api_base", "")
        if base_env:
            api_base = _resolve_env(base_env, "")
            if not api_base and default_base:
                # self-hosted: env yoksa default host kullan (localhost)
                api_base = default_base
            if api_base:
                entry["litellm_params"]["api_base"] = api_base
        elif default_base:
            entry["litellm_params"]["api_base"] = default_base

        # Yerel eklemeler için sabit api_key
        if prov.get("category") == "local" and "api_key" in prov:
            entry["litellm_params"]["api_key"] = prov["api_key"]

        model_list.append(entry)
        logger.debug("Router model eklendi: %s → %s", name, model_name)

    return model_list


def _get_router() -> Optional["Router"]:
    """
    LiteLLM Router'ı tembel (lazy) ve bir kez (singleton) oluşturur.

    Eğer litellm yüklü değilse veya etkin provider yoksa None döner.
    """
    global _router, _router_initialized
    if _router_initialized:
        return _router
    _router_initialized = True

    if not _LITELLM_AVAILABLE:
        logger.warning("litellm paketi yüklü değil → facade pas geçildi")
        return None

    config = _load_config()
    model_list = _build_model_list(config)
    if not model_list:
        logger.warning("LiteLLM Router: etkin provider yok → facade pas geçildi")
        return None

    settings = config.get("router_settings", {})
    try:
        _router = Router(
            model_list=model_list,
            routing_strategy=settings.get("routing_strategy", "simple-shuffle"),
            enable_pre_call_checks=settings.get("enable_pre_call_checks", True),
            num_retries=settings.get("num_retries", 1),
            allowed_fails=settings.get("allowed_fails", 1),
            cooldown_time=settings.get("cooldown_time", 60),
            timeout=settings.get("timeout", 30),
        )
        logger.info(
            "LiteLLM Router hazır: %d etkin provider → %s",
            len(model_list),
            ", ".join(m["model_name"] for m in model_list),
        )
    except Exception as e:
        logger.error("LiteLLM Router inşası başarısız: %s", e)
        _router = None

    return _router


# ---------------------------------------------------------------------------
# Legacy fallback (flag off veya router yoksa)
# ---------------------------------------------------------------------------
def _get_legacy_engine() -> LLMEngine:
    global _legacy_engine
    if _legacy_engine is None:
        _legacy_engine = LLMEngine()
    return _legacy_engine


def is_router_active() -> bool:
    """Facade'in LiteLLM Router'ı kullanıp kullanmadığını söyler."""
    if not is_enabled("llm_litellm_router", default=False):
        return False
    return _get_router() is not None


# ---------------------------------------------------------------------------
# Emergency template fallback (LLMEngine._emergency_fallback ile aynı iş)
# ---------------------------------------------------------------------------
def _emergency_fallback(template_key: str, context: dict[str, Any]) -> str:
    """Router'ın tüm provider'ları başarısız olduğunda template üretir."""
    try:
        from src.ai_generator import ai_title_generator
        category = context.get("category", "exciting")
        streamer = context.get("streamer_name", "Streamer")
        emotion = context.get("emotion", "exciting")

        if template_key == "title_generation":
            return ai_title_generator.generate_title(
                emotion=emotion, streamer_name=streamer, category=category,
            )
        if template_key == "description_generation":
            return ai_title_generator.generate_description(
                title=context.get("title", ""),
                streamer_name=streamer,
                category=category,
                emotion=emotion,
            )
        if template_key == "hashtag_generation":
            tags = ai_title_generator.generate_hashtags(
                category=category,
                platform=context.get("platform", "youtube"),
            )
            return json.dumps(tags)
    except Exception as e:
        logger.error("Emergency template fallback hatası: %s", e)
    return "Content generation failed. Please try again."


# ---------------------------------------------------------------------------
# JSON extraction (LLMEngine._extract_json ile aynı)
# ---------------------------------------------------------------------------
def _extract_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if not raw:
        return {"raw_output": "", "parse_error": True}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    for open_char, close_char in [('[', ']'), ('{', '}')]:
        depth = 0
        start = -1
        for i, ch in enumerate(raw):
            if ch == open_char:
                if depth == 0:
                    start = i
                depth += 1
            elif ch == close_char:
                depth -= 1
                if depth == 0 and start >= 0:
                    candidate = raw[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        start = -1
    cleaned = raw.replace("'", '"')
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"raw_output": raw, "parse_error": True}


# ---------------------------------------------------------------------------
# Prompt rendering (LLMEngine.generate ile aynı)
# ---------------------------------------------------------------------------
def _render_prompt(template_key: str, context: dict[str, Any], language: str) -> str:
    if template_key in PROMPT_TEMPLATES:
        template = PROMPT_TEMPLATES[template_key]
        ctx = dict(context or {})
        ctx.setdefault("language", "Turkish" if language == "tr" else "English")
        return template.format(**{k: ctx.get(k, "") for k in ctx})
    return template_key


# ---------------------------------------------------------------------------
# Facade API — LLMEngine.generate ile aynı imza
# ---------------------------------------------------------------------------
async def generate(
    prompt_template: str,
    language: str = "tr",
    context: dict[str, Any] | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    use_cache: bool = True,
    system_prompt: str | None = None,
) -> str:
    """
    LiteLLM Router üzerinden async completion.

    Eğer `llm_litellm_router` flag kapalıysa veya router etkin değilse
    `LLMEngine.generate`'e yönlendirir (geri uyumlu).

    Args: LLMEngine.generate ile birebir aynı.
    Returns: Üretilen metin.
    """
    ctx = context or {}

    # Path 1: flag kapalı → legacy
    if not is_enabled("llm_litellm_router", default=False):
        engine = _get_legacy_engine()
        return await engine.generate(
            prompt_template,
            language=language,
            context=ctx,
            max_tokens=max_tokens,
            temperature=temperature,
            use_cache=use_cache,
            system_prompt=system_prompt,
        )

    # Path 2: flag açık ama router kurulamadı → legacy
    router = _get_router()
    if router is None:
        engine = _get_legacy_engine()
        logger.warning("llm_litellm_router açık ama Router yok → legacy")
        return await engine.generate(
            prompt_template,
            language=language,
            context=ctx,
            max_tokens=max_tokens,
            temperature=temperature,
            use_cache=use_cache,
            system_prompt=system_prompt,
        )

    # Path 3: LiteLLM Router
    prompt = _render_prompt(prompt_template, ctx, language)
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        response = await router.acompletion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        content = response.choices[0].message.content or ""
        if len(content.strip()) > 5:
            return content
        logger.warning("LiteLLM boş yanıt → template fallback")
    except Exception as e:
        logger.warning("LiteLLM Router hatası: %s → template fallback", e)

    # Terminal fallback: template
    return _emergency_fallback(prompt_template, ctx)


async def generate_json(
    prompt_template: str,
    context: dict[str, Any] | None = None,
    language: str = "tr",
) -> dict[str, Any]:
    """Generate structured JSON (LLMEngine.generate_json ile aynı imza)."""
    raw = await generate(
        prompt_template,
        language=language,
        context=context,
        max_tokens=2048,
        temperature=0.3,
    )
    return _extract_json(raw)


async def health_check() -> dict[str, Any]:
    """
    Facade sağlık kontrolü. Hangi path'in aktif olduğunu söyler.
    """
    flag_on = is_enabled("llm_litellm_router", default=False)
    router = _get_router() if flag_on else None
    return {
        "flag_enabled": flag_on,
        "litellm_available": _LITELLM_AVAILABLE,
        "router_active": router is not None,
        "path": "litellm" if router is not None else ("legacy" if flag_on else "legacy_default"),
    }


def get_router_status() -> dict[str, Any]:
    """Router yapılandırması hakkında özet bilgi (debug/admin)."""
    config = _load_config()
    providers = config.get("tuncay_klip", {}).get("providers", {})
    enabled = [n for n, v in providers.items() if v.get("enabled")]
    return {
        "config_path": str(DEFAULT_CONFIG_PATH),
        "litellm_available": _LITELLM_AVAILABLE,
        "flag_enabled": is_enabled("llm_litellm_router", default=False),
        "router_initialized": _router is not None,
        "enabled_providers": enabled,
        "chains": list(config.get("tuncay_klip", {}).get("chains", {}).keys()),
    }
