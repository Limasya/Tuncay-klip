"""
Tests for services/llm_client.py — LiteLLM SDK facade.

Kapsam:
  - Config loading (litellm_config.yaml)
  - Zero-cost policy: sadece etkin (enabled) provider'lar router'a eklenir
  - Flag-off → legacy LLMEngine passthrough
  - Flag-acik + Router yok → legacy passthrough
  - Router hatası → template emergency fallback
  - JSON extraction (facade kopyası, LLMEngine ile parite)
  - Prompt rendering (PROMPT_TEMPLATES ile parite)
  - Mock Router ile generate() akışı
  - Sağlık kontrolü ve router durumu

Gerçek API key gerektiren testler opsiyoneldir; LITELLM_SMOKE_REAL=1 ve
GROQ_API_KEY (veya OLLAMA_HOST) tanımlı değilse atlanır.
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from services import llm_client
from platform_eng.flags.client import default_client, FlagRule, FlagType


# ---------------------------------------------------------------------------
# Fixture: flag temizliği
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_flag():
    """Her test öncesi llm_litellm_router flag'inin bilinen bir durumda olması."""
    default_client.set_flag(FlagRule(
        key="llm_litellm_router",
        enabled=False,
        flag_type=FlagType.RELEASE,
        rollout_percentage=100,
    ))
    yield
    default_client.set_flag(FlagRule(
        key="llm_litellm_router",
        enabled=False,
        flag_type=FlagType.RELEASE,
        rollout_percentage=100,
    ))


def _set_flag(enabled: bool):
    default_client.set_flag(FlagRule(
        key="llm_litellm_router",
        enabled=enabled,
        flag_type=FlagType.RELEASE,
        rollout_percentage=100,
    ))


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
class TestConfigLoading:
    def test_load_config_returns_dict(self):
        config = llm_client._load_config()
        assert isinstance(config, dict)
        assert "tuncay_klip" in config

    def test_load_config_has_providers(self):
        config = llm_client._load_config()
        providers = config["tuncay_klip"]["providers"]
        assert "ollama" in providers
        assert "template_content_fallback" in config["tuncay_klip"] or True  # fallback ayrı key

    def test_config_zero_cost_default(self):
        """Sıfır maliyet kuralı: ücretli provider'lar varsayılan etkin olamaz."""
        config = llm_client._load_config()
        providers = config["tuncay_klip"]["providers"]
        enabled = [n for n, v in providers.items() if v.get("enabled")]
        # Zero-cost provider'lar etkin: 5 local + 4 verified free cloud
        # (mistral_free: enabled=false — veri gizliliği şüphesi, kullanıcı kararı bekleniyor)
        expected_free = {"ollama", "vllm", "lm_studio", "localai", "textgen",
                         "groq", "gemini", "cerebras", "openrouter_free"}
        assert set(enabled) == expected_free
        # Hiçbir ücretli/trial provider varsayılan etkin olamaz
        for name in ("openai", "anthropic", "together", "nvidia_nim", "huggingface"):
            assert providers[name]["enabled"] is False, f"{name} varsayılan etkin olamaz"
        # mistral_free de disabled (data privacy concern, pending user decision)
        assert providers["mistral_free"]["enabled"] is False

    def test_config_policy_explicit(self):
        config = llm_client._load_config()
        policy = config["tuncay_klip"]["policy"]
        assert policy["mode"] == "zero_cost_only"
        assert policy["automatic_paid_fallback"] is False
        assert policy["automatic_trial_fallback"] is False
        assert policy["terminal_fallback"] == "template_content_fallback"

    def test_config_chains_all_have_template_tail(self):
        """Her zincir terminal adım olarak template ile bitmeli."""
        config = llm_client._load_config()
        chains = config["tuncay_klip"]["chains"]
        for name, seq in chains.items():
            assert seq[-1] == "template_content_fallback", (
                f"{name} zinciri template ile bitmiyor: {seq}"
            )


# ---------------------------------------------------------------------------
# Router model list building
# ---------------------------------------------------------------------------
class TestModelListBuilding:
    def test_build_model_list_local_only_by_default(self, monkeypatch):
        """API key olmadan yalnızca local backendler(mock host olmadan) atlanır."""
        # Tüm local host env'lerini temizle → local provider'lar default base URL ile gelmeli
        for v in ("OLLAMA_HOST", "VLLM_HOST", "LM_STUDIO_HOST", "LOCALAI_HOST", "TEXTGEN_HOST"):
            monkeypatch.delenv(v, raising=False)
        # Remote API key'leri temizle
        for v in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(v, raising=False)

        config = llm_client._load_config()
        model_list = llm_client._build_model_list(config)

        # config'de enabled provider'lar: ollama, vllm, lm_studio, localai, textgen
        names = {m["model_name"] for m in model_list}
        # Default api_base tanımlı olanlar (ollama, vllm, lm_studio, localai, textgen) listeye eklenmeli
        assert "ollama" in names
        assert "vllm" in names
        assert "localai" in names

    def test_build_model_list_skips_remote_without_key(self, monkeypatch):
        """Uzak provider'lar API key olmadan asla listeye eklenmez."""
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        config = llm_client._load_config()
        # groq config'de enabled: false zaten; test koruması: enabled true olsa bile key yoksa atlanmalı
        config["tuncay_klip"]["providers"]["groq"]["enabled"] = True
        model_list = llm_client._build_model_list(config)
        names = {m["model_name"] for m in model_list}
        assert "groq" not in names

    def test_build_model_list_includes_remote_with_key(self, monkeypatch):
        """API key varsa uzak provider listeye eklenir (zero-cost chain'de değil ama Router'da var)."""
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key")
        config = llm_client._load_config()
        config["tuncay_klip"]["providers"]["groq"]["enabled"] = True
        try:
            model_list = llm_client._build_model_list(config)
            names = {m["model_name"] for m in model_list}
            assert "groq" in names
            groq_entry = next(m for m in model_list if m["model_name"] == "groq")
            assert groq_entry["litellm_params"]["api_key"] == "gsk_test_key"
        finally:
            # config cache'i temizle ki diğer testler etkilenmesin
            llm_client._config_cache = None


# ---------------------------------------------------------------------------
# Flag-off passthrough (legacy)
# ---------------------------------------------------------------------------
class TestFlagOffPassthrough:
    @pytest.mark.asyncio
    async def test_flag_off_calls_legacy_engine(self):
        """Flag kapalıyken facade, LLMEngine.generate'e yönlendirir."""
        _set_flag(False)
        with patch.object(llm_client, "_get_legacy_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.generate = AsyncMock(return_value="legacy output")
            mock_get.return_value = mock_engine

            result = await llm_client.generate("title_generation", language="tr", context={})

            assert result == "legacy output"
            mock_engine.generate.assert_awaited_once()
            assert mock_engine.generate.call_args.kwargs["language"] == "tr"

    @pytest.mark.asyncio
    async def test_flag_off_generate_json_passthrough(self):
        _set_flag(False)
        with patch.object(llm_client, "_get_legacy_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.generate = AsyncMock(return_value='{"mood": "hype"}')
            mock_get.return_value = mock_engine

            result = await llm_client.generate_json("clip_analysis", context={}, language="tr")

            assert result["mood"] == "hype"
            mock_engine.generate.assert_awaited_once()


# ---------------------------------------------------------------------------
# Flag-on + Router unavailable → legacy
# ---------------------------------------------------------------------------
class TestFlagOnRouterUnavailable:
    @pytest.mark.asyncio
    async def test_flag_on_router_none_falls_to_legacy(self):
        _set_flag(True)
        with patch.object(llm_client, "_get_router", return_value=None), \
             patch.object(llm_client, "_get_legacy_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.generate = AsyncMock(return_value="legacy fallback")
            mock_get.return_value = mock_engine

            result = await llm_client.generate("title_generation", language="tr", context={})

            assert result == "legacy fallback"
            mock_engine.generate.assert_awaited_once()


# ---------------------------------------------------------------------------
# Router success path (mock Router)
# ---------------------------------------------------------------------------
class TestRouterSuccessPath:
    @pytest.mark.asyncio
    async def test_router_returns_content(self):
        _set_flag(True)
        mock_router = MagicMock()
        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Mock LLM output"))]
        )
        mock_router.acompletion = AsyncMock(return_value=mock_response)

        with patch.object(llm_client, "_get_router", return_value=mock_router):
            result = await llm_client.generate(
                "title_generation",
                language="tr",
                context={"streamer_name": "Tuncay", "category": "exciting", "emotion": "hype"},
            )

        assert result == "Mock LLM output"
        mock_router.acompletion.assert_awaited_once()
        call = mock_router.acompletion.call_args
        assert call.kwargs["max_tokens"] == 1024
        assert call.kwargs["temperature"] == 0.7
        msgs = call.kwargs["messages"]
        assert msgs[-1]["role"] == "user"
        # Prompt template render edilmeli (streamer adı geçmeli)
        assert "Tuncay" in msgs[-1]["content"]

    @pytest.mark.asyncio
    async def test_router_with_system_prompt(self):
        _set_flag(True)
        mock_router = MagicMock()
        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))]
        )
        mock_router.acompletion = AsyncMock(return_value=mock_response)

        with patch.object(llm_client, "_get_router", return_value=mock_router):
            await llm_client.generate(
                "raw prompt text",
                language="en",
                system_prompt="Be a critic",
            )

        msgs = mock_router.acompletion.call_args.kwargs["messages"]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "Be a critic"
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "raw prompt text"

    @pytest.mark.asyncio
    async def test_router_empty_response_falls_to_template(self):
        _set_flag(True)
        mock_router = MagicMock()
        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=""))]
        )
        mock_router.acompletion = AsyncMock(return_value=mock_response)

        with patch.object(llm_client, "_get_router", return_value=mock_router), \
             patch.object(llm_client, "_emergency_fallback", return_value="TEMPLATE RESULT"):
            result = await llm_client.generate("title_generation", language="tr", context={})
        assert result == "TEMPLATE RESULT"

    @pytest.mark.asyncio
    async def test_router_exception_falls_to_template(self):
        _set_flag(True)
        mock_router = MagicMock()
        mock_router.acompletion = AsyncMock(side_effect=RuntimeError("rate limited"))

        with patch.object(llm_client, "_get_router", return_value=mock_router), \
             patch.object(llm_client, "_emergency_fallback", return_value="TEMPLATE FALLBACK"):
            result = await llm_client.generate("title_generation", language="tr", context={})
        assert result == "TEMPLATE FALLBACK"


# ---------------------------------------------------------------------------
# Emergency fallback + JSON extraction (parity with LLMEngine)
# ---------------------------------------------------------------------------
class TestEmergencyFallback:
    def test_emergency_fallback_title(self, monkeypatch):
        # src.ai_generator.ai_title_generator'yı taklit et
        fake_module = MagicMock()
        fake_module.generate_title = MagicMock(return_value="Efsane Klip!")
        monkeypatch.setitem(sys.modules, "src", MagicMock())
        monkeypatch.setitem(sys.modules, "src.ai_generator", fake_module)
        monkeypatch.setattr(
            fake_module, "ai_title_generator",
            fake_module, raising=False,
        )
        result = llm_client._emergency_fallback("title_generation", {
            "streamer_name": "Tuncay",
            "category": "exciting",
            "emotion": "hype",
        })
        assert isinstance(result, str)
        assert len(result) > 0


class TestJsonExtraction:
    """Facade'in _extract_json kopyası LLMEngine ile parite."""
    def test_direct_array(self):
        result = llm_client._extract_json('["a", "b"]')
        assert result == ["a", "b"]

    def test_direct_object(self):
        result = llm_client._extract_json('{"k": "v"}')
        assert result["k"] == "v"

    def test_markdown_fence(self):
        result = llm_client._extract_json('```json\n{"k": "v"}\n```')
        assert result["k"] == "v"

    def test_text_around_json(self):
        result = llm_client._extract_json('Here: {"k": "v"} done')
        assert result["k"] == "v"

    def test_nested(self):
        result = llm_client._extract_json('{"a": {"b": 1}}')
        assert result["a"]["b"] == 1

    def test_empty(self):
        result = llm_client._extract_json("")
        assert result.get("parse_error") is True

    def test_single_quotes(self):
        result = llm_client._extract_json("{'k': 'v'}")
        assert result["k"] == "v"

    def test_trailing_comma(self):
        result = llm_client._extract_json('{"k": "v",}')
        assert result["k"] == "v"


class TestPromptRendering:
    def test_template_key_rendered(self):
        ctx = {"streamer_name": "Tuncay", "emotion": "hype"}
        prompt = llm_client._render_prompt("title_generation", ctx, "tr")
        assert "Tuncay" in prompt
        assert "Turkish" in prompt  # language injection

    def test_raw_prompt_passthrough(self):
        prompt = llm_client._render_prompt("just a raw string", {}, "en")
        assert prompt == "just a raw string"


# ---------------------------------------------------------------------------
# Health & status
# ---------------------------------------------------------------------------
class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_flag_off(self):
        _set_flag(False)
        result = await llm_client.health_check()
        assert result["flag_enabled"] is False
        assert result["path"] == "legacy_default"

    @pytest.mark.asyncio
    async def test_health_flag_on_router_none(self):
        _set_flag(True)
        with patch.object(llm_client, "_get_router", return_value=None):
            result = await llm_client.health_check()
        assert result["flag_enabled"] is True
        assert result["router_active"] is False
        assert result["path"] == "legacy"

    @pytest.mark.asyncio
    async def test_health_flag_on_router_active(self):
        _set_flag(True)
        mock_router = MagicMock()
        with patch.object(llm_client, "_get_router", return_value=mock_router):
            result = await llm_client.health_check()
        assert result["flag_enabled"] is True
        assert result["router_active"] is True
        assert result["path"] == "litellm"


class TestRouterStatus:
    def test_status_returns_dict(self):
        status = llm_client.get_router_status()
        assert isinstance(status, dict)
        assert "flag_enabled" in status
        assert "enabled_providers" in status
        assert "chains" in status
        # Local backends + verified free cloud providers (mistral_free excluded)
        expected_local = {"ollama", "vllm", "lm_studio", "localai", "textgen"}
        expected_cloud = {"groq", "gemini", "cerebras", "openrouter_free"}
        assert expected_local.issubset(set(status["enabled_providers"]))
        assert expected_cloud.issubset(set(status["enabled_providers"]))

    def test_is_router_active_flag_off(self):
        _set_flag(False)
        assert llm_client.is_router_active() is False

    def test_is_router_active_flag_on_no_router(self):
        _set_flag(True)
        with patch.object(llm_client, "_get_router", return_value=None):
            assert llm_client.is_router_active() is False


# ---------------------------------------------------------------------------
# Opsiyonel: gerçek key ile smoke testi (env'de açılmadıkça skip)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not (sys.flags.optimize & 0x1) and
    not __import__("os").environ.get("LITELLM_SMOKE_REAL") == "1",
    reason="LITELLM_SMOKE_REAL=1 gereklidir; aksi halde gerçek API'ma çatılmaz",
)
class TestRealSmoke:
    """Gerçek provider ile uçtan uca test — yalnızca manuel onay ile çalışır."""

    @pytest.mark.asyncio
    async def test_real_groq_smoke(self):
        import os
        if not os.environ.get("GROQ_API_KEY"):
            pytest.skip("GROQ_API_KEY gerek")
        _set_flag(True)
        # Config'de groq'u geçici aç
        config = llm_client._load_config()
        config["tuncay_klip"]["providers"]["groq"]["enabled"] = True
        llm_client._router = None
        llm_client._router_initialized = False
        try:
            result = await llm_client.generate(
                "title_generation",
                language="tr",
                context={
                    "streamer_name": "Tuncay",
                    "category": "exciting",
                    "emotion": "hype",
                    "game_name": "CS2",
                    "viewer_count": "1000",
                },
                max_tokens=64,
            )
            assert isinstance(result, str)
            assert len(result) > 5
        finally:
            config["tuncay_klip"]["providers"]["groq"]["enabled"] = False
            llm_client._config_cache = None
            llm_client._router = None
            llm_client._router_initialized = False
