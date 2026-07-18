"""
Provider Adapter — Ortak LLM Provider Arayüzü
──────────────────────────────────────────────
17 provider'ı tek bir arayüzde birleştirir.
Her provider için ayrı if/else bloğu yerine,
ProviderAdapter + Capability Matrix kullanılır.

Akış:
  Config → Capability Matrix → Provider Selection → Adapter → API Call → Response

Yeni provider eklemek = yeni bir Adapter sınıfı + matrix satırı.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional

import httpx

logger = logging.getLogger("llm.adapter")


# ── Capability Matrix ──

class ProviderTier(int, Enum):
    """Provider fiyat/performans seviyesi."""
    FREE = 1           # Tamamen ücretsiz (Groq, Cerebras)
    FREEMIUM = 2       # Ücretsiz tier var (Gemini, Mistral, OpenRouter)
    PAID = 3           # Ücretli (OpenAI, Claude)
    LOCAL = 4          # Yerel (Ollama, vLLM, LM Studio)
    FALLBACK = 99      # Son çare (Template)


class Capability(str, Enum):
    """Provider'ın desteklediği yetenekler."""
    CHAT = "chat"
    COMPLETION = "completion"
    STREAMING = "streaming"
    JSON_MODE = "json_mode"
    VISION = "vision"
    AUDIO = "audio"
    EMBEDDING = "embedding"
    SYSTEM_PROMPT = "system_prompt"
    MULTI_MODAL = "multi_modal"


@dataclass
class ProviderCapabilities:
    """Bir provider'ın yetenek matrisi."""
    name: str
    tier: ProviderTier
    api_format: str  # "openai", "anthropic", "gemini", "ollama", "cohere", "huggingface", "template"
    capabilities: set[Capability] = field(default_factory=lambda: {Capability.CHAT})
    models: list[str] = field(default_factory=list)
    default_model: str = ""
    speed_toks_per_sec: float = 0.0
    max_tokens: int = 4096
    rate_limit_rpm: int = 0
    rate_limit_tpd: int = 0
    supports_system_prompt: bool = True
    supports_json_mode: bool = False
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    env_key: str = ""
    env_model: str = ""
    base_url: str = ""
    timeout: float = 60.0

    @property
    def is_available(self) -> bool:
        """Env değişkeni doluysa veya local provider'sa müsait."""
        import os
        if self.tier == ProviderTier.LOCAL:
            return bool(os.environ.get(self.env_key, ""))
        if self.tier == ProviderTier.FALLBACK:
            return True
        return bool(os.environ.get(self.env_key, ""))

    @property
    def score(self) -> float:
        """Provider sıralama skoru (yüksek = iyi)."""
        tier_bonus = {
            ProviderTier.FREE: 10,
            ProviderTier.FREEMIUM: 7,
            ProviderTier.PAID: 5,
            ProviderTier.LOCAL: 8,
            ProviderTier.FALLBACK: 1,
        }
        return tier_bonus.get(self.tier, 0) + self.speed_toks_per_sec / 100


# ── Capability Matrix ──

CAPABILITY_MATRIX: dict[str, ProviderCapabilities] = {
    "openai": ProviderCapabilities(
        name="openai",
        tier=ProviderTier.PAID,
        api_format="openai",
        models=["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
        default_model="gpt-4o-mini",
        speed_toks_per_sec=80,
        max_tokens=4096,
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.0006,
        env_key="OPENAI_API_KEY",
        env_model="OPENAI_MODEL",
    ),
    "anthropic": ProviderCapabilities(
        name="anthropic",
        tier=ProviderTier.PAID,
        api_format="anthropic",
        models=["claude-3-haiku-20240307", "claude-3-sonnet-20240229", "claude-3-opus-20240229"],
        default_model="claude-3-haiku-20240307",
        speed_toks_per_sec=60,
        max_tokens=4096,
        cost_per_1k_input=0.00025,
        cost_per_1k_output=0.00125,
        env_key="ANTHROPIC_API_KEY",
        env_model="CLAUDE_MODEL",
    ),
    "gemini": ProviderCapabilities(
        name="gemini",
        tier=ProviderTier.FREEMIUM,
        api_format="gemini",
        models=["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        default_model="gemini-2.0-flash",
        speed_toks_per_sec=100,
        max_tokens=8192,
        rate_limit_rpm=15,
        rate_limit_tpd=1_000_000,
        env_key="GEMINI_API_KEY",
        env_model="GEMINI_MODEL",
    ),
    "mistral": ProviderCapabilities(
        name="mistral",
        tier=ProviderTier.FREEMIUM,
        api_format="openai",
        models=["mistral-small-latest", "mistral-medium-latest"],
        default_model="mistral-small-latest",
        speed_toks_per_sec=60,
        max_tokens=4096,
        env_key="MISTRAL_API_KEY",
        env_model="MISTRAL_MODEL",
    ),
    "groq": ProviderCapabilities(
        name="groq",
        tier=ProviderTier.FREE,
        api_format="openai",
        models=["llama-3.1-70b-versatile", "llama3-70b-8192", "mixtral-8x7b-32768", "gemma2-9b-it"],
        default_model="llama-3.1-70b-versatile",
        speed_toks_per_sec=800,
        max_tokens=8192,
        rate_limit_rpm=30,
        rate_limit_tpd=14_400,
        supports_json_mode=True,
        env_key="GROQ_API_KEY",
        env_model="GROQ_MODEL",
    ),
    "cohere": ProviderCapabilities(
        name="cohere",
        tier=ProviderTier.FREEMIUM,
        api_format="cohere",
        models=["command-r", "command-r-plus"],
        default_model="command-r",
        speed_toks_per_sec=50,
        max_tokens=4096,
        rate_limit_tpd=1000,
        env_key="COHERE_API_KEY",
        env_model="COHERE_MODEL",
    ),
    "together": ProviderCapabilities(
        name="together",
        tier=ProviderTier.FREEMIUM,
        api_format="openai",
        models=["meta-llama/Llama-3.1-70B-Instruct-Turbo", "meta-llama/Llama-3.1-8B-Instruct-Turbo"],
        default_model="meta-llama/Llama-3.1-70B-Instruct-Turbo",
        speed_toks_per_sec=70,
        max_tokens=4096,
        env_key="TOGETHER_API_KEY",
        env_model="TOGETHER_MODEL",
        base_url="https://api.together.xyz",
    ),
    "cerebras": ProviderCapabilities(
        name="cerebras",
        tier=ProviderTier.FREE,
        api_format="openai",
        models=["llama3.1-70b", "llama3.1-8b"],
        default_model="llama3.1-70b",
        speed_toks_per_sec=2000,
        max_tokens=8192,
        env_key="CEREBRAS_API_KEY",
        env_model="CEREBRAS_MODEL",
        base_url="https://api.cerebras.ai/v1",
    ),
    "openrouter": ProviderCapabilities(
        name="openrouter",
        tier=ProviderTier.FREE,
        api_format="openai",
        models=["meta-llama/llama-3.1-8b-instruct:free", "meta-llama/llama-3.1-70b-instruct:free"],
        default_model="meta-llama/llama-3.1-8b-instruct:free",
        speed_toks_per_sec=60,
        max_tokens=4096,
        env_key="OPENROUTER_API_KEY",
        env_model="OPENROUTER_MODEL",
        base_url="https://openrouter.ai/api/v1",
    ),
    "nvidia": ProviderCapabilities(
        name="nvidia",
        tier=ProviderTier.FREEMIUM,
        api_format="openai",
        models=["meta/llama-3.1-70b-instruct"],
        default_model="meta/llama-3.1-70b-instruct",
        speed_toks_per_sec=80,
        max_tokens=4096,
        env_key="NVIDIA_API_KEY",
        env_model="NVIDIA_MODEL",
        base_url="https://integrate.api.nvidia.com/v1",
    ),
    "huggingface": ProviderCapabilities(
        name="huggingface",
        tier=ProviderTier.FREEMIUM,
        api_format="huggingface",
        models=["HuggingFaceH4/zephyr-7b-beta"],
        default_model="HuggingFaceH4/zephyr-7b-beta",
        speed_toks_per_sec=30,
        max_tokens=2048,
        rate_limit_tpd=1000,
        env_key="HUGGINGFACE_API_TOKEN",
        env_model="HUGGINGFACE_MODEL",
    ),
    "ollama": ProviderCapabilities(
        name="ollama",
        tier=ProviderTier.LOCAL,
        api_format="ollama",
        models=["llama3.1:8b", "llama3.1:70b", "mistral", "codellama"],
        default_model="llama3.1:8b",
        speed_toks_per_sec=20,
        max_tokens=4096,
        env_key="OLLAMA_HOST",
        env_model="OLLAMA_MODEL",
        timeout=120.0,
    ),
    "vllm": ProviderCapabilities(
        name="vllm",
        tier=ProviderTier.LOCAL,
        api_format="openai",
        models=["meta-llama/Llama-3-8B-Instruct"],
        default_model="meta-llama/Llama-3-8B-Instruct",
        speed_toks_per_sec=60,
        max_tokens=4096,
        env_key="VLLM_HOST",
        env_model="VLLM_MODEL",
    ),
    "lm_studio": ProviderCapabilities(
        name="lm_studio",
        tier=ProviderTier.LOCAL,
        api_format="openai",
        models=["default"],
        default_model="default",
        speed_toks_per_sec=20,
        max_tokens=4096,
        env_key="LM_STUDIO_HOST",
        env_model="LM_STUDIO_MODEL",
    ),
    "localai": ProviderCapabilities(
        name="localai",
        tier=ProviderTier.LOCAL,
        api_format="openai",
        models=["gpt-3.5-turbo"],
        default_model="gpt-3.5-turbo",
        speed_toks_per_sec=15,
        max_tokens=4096,
        env_key="LOCALAI_HOST",
        env_model="LOCALAI_MODEL",
    ),
    "textgen": ProviderCapabilities(
        name="textgen",
        tier=ProviderTier.LOCAL,
        api_format="openai",
        models=["default"],
        default_model="default",
        speed_toks_per_sec=15,
        max_tokens=4096,
        env_key="TEXTGEN_HOST",
        env_model="TEXTGEN_MODEL",
    ),
    "template": ProviderCapabilities(
        name="template",
        tier=ProviderTier.FALLBACK,
        api_format="template",
        models=["template"],
        default_model="template",
        speed_toks_per_sec=9999,
        max_tokens=0,
        env_key="",
        env_model="",
    ),
}


# ── Provider Adapter (Abstract) ──

@dataclass
class LLMResponse:
    """Standart LLM response."""
    text: str = ""
    model: str = ""
    provider: str = ""
    tokens_used: int = 0
    latency_ms: float = 0
    from_cache: bool = False
    error: str = ""


class ProviderAdapter(ABC):
    """Tüm provider'lar için ortak arayüz."""

    def __init__(self, caps: ProviderCapabilities):
        self.caps = caps
        self._client: Optional[httpx.AsyncClient] = None
        self._success_count: int = 0
        self._error_count: int = 0
        self._total_tokens: int = 0
        self._cooldown_until: float = 0

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system_prompt: str = "",
        **kwargs,
    ) -> LLMResponse:
        """Metin üret."""
        ...

    @property
    def is_available(self) -> bool:
        if self._cooldown_until > time.time():
            return False
        return self.caps.is_available

    @property
    def success_rate(self) -> float:
        total = self._success_count + self._error_count
        return self._success_count / total if total > 0 else 1.0

    def record_success(self, tokens: int):
        self._success_count += 1
        self._total_tokens += tokens
        self._cooldown_until = 0

    def record_error(self):
        self._error_count += 1
        if self._error_count >= 3:
            self._cooldown_until = time.time() + 60
            logger.warning("Provider '%s' cooldown for 60s (3+ errors)", self.caps.name)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ── OpenAI-Compatible Adapter ──

class OpenAICompatibleAdapter(ProviderAdapter):
    """OpenAI API formatındaki provider'lar için ortak adapter."""

    def __init__(self, caps: ProviderCapabilities, base_url: str = "", api_key: str = ""):
        super().__init__(caps)
        self._base_url = base_url or self._resolve_base_url()
        self._api_key = api_key

    def _resolve_base_url(self) -> str:
        import os
        host = os.environ.get(self.caps.env_key.replace("_API_KEY", "_HOST").replace("_TOKEN", "_HOST"), "")
        if host:
            base = host.rstrip("/")
            if not base.startswith("http"):
                base = f"http://{base}"
            if not base.endswith("/v1"):
                base += "/v1"
            return base
        if self.caps.base_url:
            return self.caps.base_url.rstrip("/") + "/v1"
        return "https://api.openai.com/v1"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            import os
            key = self._api_key or os.environ.get(self.caps.env_key, "")
            self._client = httpx.AsyncClient(
                timeout=self.caps.timeout,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system_prompt: str = "",
        **kwargs,
    ) -> LLMResponse:
        import os
        model = kwargs.get("model", os.environ.get(self.caps.env_model, self.caps.default_model))
        start = time.time()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        # JSON mode for Groq
        if self.caps.supports_json_mode and kwargs.get("json_mode"):
            payload["response_format"] = {"type": "json_object"}

        try:
            client = await self._get_client()
            response = await client.post(f"{self._base_url}/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            text = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", 0)
            latency = (time.time() - start) * 1000

            self.record_success(tokens)
            return LLMResponse(
                text=text,
                model=model,
                provider=self.caps.name,
                tokens_used=tokens,
                latency_ms=latency,
            )
        except Exception as e:
            self.record_error()
            return LLMResponse(
                text="",
                model=model,
                provider=self.caps.name,
                error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )


# ── Anthropic Adapter ──

class AnthropicAdapter(ProviderAdapter):
    """Anthropic Claude API adapter."""

    def __init__(self, caps: ProviderCapabilities):
        super().__init__(caps)

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system_prompt: str = "",
        **kwargs,
    ) -> LLMResponse:
        import os
        model = kwargs.get("model", os.environ.get(self.caps.env_model, self.caps.default_model))
        start = time.time()

        try:
            if self._client is None or self._client.is_closed:
                key = os.environ.get(self.caps.env_key, "")
                self._client = httpx.AsyncClient(
                    timeout=self.caps.timeout,
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                )

            payload: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system_prompt:
                payload["system"] = system_prompt

            response = await self._client.post(
                "https://api.anthropic.com/v1/messages", json=payload
            )
            response.raise_for_status()
            data = response.json()

            text = data["content"][0]["text"]
            tokens = data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get("output_tokens", 0)
            latency = (time.time() - start) * 1000

            self.record_success(tokens)
            return LLMResponse(
                text=text, model=model, provider=self.caps.name,
                tokens_used=tokens, latency_ms=latency,
            )
        except Exception as e:
            self.record_error()
            return LLMResponse(
                text="", model=model, provider=self.caps.name,
                error=str(e), latency_ms=(time.time() - start) * 1000,
            )


# ── Gemini Adapter ──

class GeminiAdapter(ProviderAdapter):
    """Google Gemini API adapter."""

    def __init__(self, caps: ProviderCapabilities):
        super().__init__(caps)

    async def generate(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str = "", **kwargs,
    ) -> LLMResponse:
        import os
        model = kwargs.get("model", os.environ.get(self.caps.env_model, self.caps.default_model))
        start = time.time()

        try:
            if self._client is None or self._client.is_closed:
                key = os.environ.get(self.caps.env_key, "")
                self._client = httpx.AsyncClient(timeout=self.caps.timeout)

            messages = []
            if system_prompt:
                messages.append({"role": "user", "parts": [{"text": system_prompt}]})
                messages.append({"role": "model", "parts": [{"text": "Understood."}]})
            messages.append({"role": "user", "parts": [{"text": prompt}]})

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={os.environ.get(self.caps.env_key, '')}"
            response = await self._client.post(url, json={"contents": messages})
            response.raise_for_status()
            data = response.json()

            text = data["candidates"][0]["content"]["parts"][0]["text"]
            tokens = data.get("usageMetadata", {}).get("totalTokenCount", 0)
            latency = (time.time() - start) * 1000

            self.record_success(tokens)
            return LLMResponse(
                text=text, model=model, provider=self.caps.name,
                tokens_used=tokens, latency_ms=latency,
            )
        except Exception as e:
            self.record_error()
            return LLMResponse(
                text="", model=model, provider=self.caps.name,
                error=str(e), latency_ms=(time.time() - start) * 1000,
            )


# ── Cohere Adapter ──

class CohereAdapter(ProviderAdapter):
    """Cohere API adapter."""

    def __init__(self, caps: ProviderCapabilities):
        super().__init__(caps)

    async def generate(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str = "", **kwargs,
    ) -> LLMResponse:
        import os
        model = kwargs.get("model", os.environ.get(self.caps.env_model, self.caps.default_model))
        start = time.time()

        try:
            if self._client is None or self._client.is_closed:
                key = os.environ.get(self.caps.env_key, "")
                self._client = httpx.AsyncClient(
                    timeout=self.caps.timeout,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                )

            messages = []
            if system_prompt:
                messages.append({"role": "SYSTEM", "message": system_prompt})
            messages.append({"role": "USER", "message": prompt})

            response = await self._client.post(
                "https://api.cohere.com/v2/chat",
                json={"model": model, "messages": messages},
            )
            response.raise_for_status()
            data = response.json()

            text = data["message"]["content"][0]["text"]
            tokens = data.get("meta", {}).get("tokens", {}).get("input_tokens", 0) + \
                     data.get("meta", {}).get("tokens", {}).get("output_tokens", 0)
            latency = (time.time() - start) * 1000

            self.record_success(tokens)
            return LLMResponse(
                text=text, model=model, provider=self.caps.name,
                tokens_used=tokens, latency_ms=latency,
            )
        except Exception as e:
            self.record_error()
            return LLMResponse(
                text="", model=model, provider=self.caps.name,
                error=str(e), latency_ms=(time.time() - start) * 1000,
            )


# ── Ollama Adapter ──

class OllamaAdapter(ProviderAdapter):
    """Ollama local API adapter."""

    def __init__(self, caps: ProviderCapabilities):
        super().__init__(caps)

    async def generate(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str = "", **kwargs,
    ) -> LLMResponse:
        import os
        model = kwargs.get("model", os.environ.get(self.caps.env_model, self.caps.default_model))
        start = time.time()

        try:
            host = os.environ.get(self.caps.env_key, "http://localhost:11434")
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(timeout=self.caps.timeout)

            payload: dict[str, Any] = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            }
            if system_prompt:
                payload["system"] = system_prompt

            response = await self._client.post(f"{host.rstrip('/')}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()

            text = data.get("response", "")
            tokens = data.get("eval_count", 0)
            latency = (time.time() - start) * 1000

            self.record_success(tokens)
            return LLMResponse(
                text=text, model=model, provider=self.caps.name,
                tokens_used=tokens, latency_ms=latency,
            )
        except Exception as e:
            self.record_error()
            return LLMResponse(
                text="", model=model, provider=self.caps.name,
                error=str(e), latency_ms=(time.time() - start) * 1000,
            )


# ── HuggingFace Adapter ──

class HuggingFaceAdapter(ProviderAdapter):
    """HuggingFace Inference API adapter."""

    def __init__(self, caps: ProviderCapabilities):
        super().__init__(caps)

    async def generate(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str = "", **kwargs,
    ) -> LLMResponse:
        import os
        model = kwargs.get("model", os.environ.get(self.caps.env_model, self.caps.default_model))
        start = time.time()

        try:
            if self._client is None or self._client.is_closed:
                token = os.environ.get(self.caps.env_key, "")
                self._client = httpx.AsyncClient(
                    timeout=self.caps.timeout,
                    headers={"Authorization": f"Bearer {token}"},
                )

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            url = f"https://api-inference.huggingface.co/models/{model}/v1/chat/completions"
            response = await self._client.post(url, json={
                "model": model, "messages": messages, "max_tokens": max_tokens,
                "temperature": temperature, "stream": False,
            })
            response.raise_for_status()
            data = response.json()

            text = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", 0)
            latency = (time.time() - start) * 1000

            self.record_success(tokens)
            return LLMResponse(
                text=text, model=model, provider=self.caps.name,
                tokens_used=tokens, latency_ms=latency,
            )
        except Exception as e:
            self.record_error()
            return LLMResponse(
                text="", model=model, provider=self.caps.name,
                error=str(e), latency_ms=(time.time() - start) * 1000,
            )


# ── Template Adapter (Fallback) ──

class TemplateAdapter(ProviderAdapter):
    """Kural tabanlı fallback adapter — her zaman çalışır."""

    def __init__(self, caps: ProviderCapabilities):
        super().__init__(caps)

    async def generate(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str = "", **kwargs,
    ) -> LLMResponse:
        # Template provider kural tabanlı üretim yapar
        task = kwargs.get("task", "title")
        text = self._generate_template(prompt, task)
        self.record_success(0)
        return LLMResponse(text=text, model="template", provider="template", latency_ms=0)

    def _generate_template(self, prompt: str, task: str) -> str:
        import random
        if task == "title":
            templates = [
                "EPIC {} MOMENT! 🔥", "ABSOLUTELY INSANE {} PLAY", "{} GOES CRAZY!",
                "THIS {} PLAY IS UNREAL", "NO WAY {} DID THIS",
            ]
            return random.choice(templates).format(random.choice(["VALORANT", "CS2", "GAMING", "STREAM"]))
        elif task == "hashtag":
            return "#gaming #streamer #valo #clip #epic #highlight #viral"
        else:
            return "Amazing stream moment!"


# ── Adapter Factory ──

ADAPTER_MAP: dict[str, type[ProviderAdapter]] = {
    "openai": OpenAICompatibleAdapter,
    "anthropic": AnthropicAdapter,
    "gemini": GeminiAdapter,
    "mistral": OpenAICompatibleAdapter,
    "groq": OpenAICompatibleAdapter,
    "cohere": CohereAdapter,
    "together": OpenAICompatibleAdapter,
    "cerebras": OpenAICompatibleAdapter,
    "openrouter": OpenAICompatibleAdapter,
    "nvidia": OpenAICompatibleAdapter,
    "huggingface": HuggingFaceAdapter,
    "ollama": OllamaAdapter,
    "vllm": OpenAICompatibleAdapter,
    "lm_studio": OpenAICompatibleAdapter,
    "localai": OpenAICompatibleAdapter,
    "textgen": OpenAICompatibleAdapter,
    "template": TemplateAdapter,
}


def create_adapter(provider_name: str) -> Optional[ProviderAdapter]:
    """Provider adından adapter oluştur."""
    caps = CAPABILITY_MATRIX.get(provider_name)
    if not caps:
        return None

    adapter_cls = ADAPTER_MAP.get(caps.api_format, OpenAICompatibleAdapter)

    if caps.api_format == "openai" and provider_name not in ("openai",):
        # OpenAI-compatible providers need base_url
        import os
        host = os.environ.get(caps.env_key.replace("_API_KEY", "_HOST").replace("_TOKEN", "_HOST"), "")
        return adapter_cls(caps, base_url=host or caps.base_url)

    return adapter_cls(caps)


def get_available_providers() -> list[ProviderCapabilities]:
    """Mevcut provider'ları listele."""
    return [caps for caps in CAPABILITY_MATRIX.values() if caps.is_available]


def get_providers_by_tier(tier: ProviderTier) -> list[ProviderCapabilities]:
    """Tier'a göre provider'ları listele."""
    return [caps for caps in CAPABILITY_MATRIX.values()
            if caps.tier == tier and caps.is_available]


def select_best_provider(
    task: str = "chat",
    prefer_free: bool = True,
    prefer_speed: bool = False,
) -> Optional[ProviderCapabilities]:
    """En uygun provider'ı seç."""
    available = get_available_providers()
    if not available:
        return None

    # Filtreleme
    candidates = [p for p in available if p.tier != ProviderTier.FALLBACK]
    if not candidates:
        candidates = available

    # Sıralama
    if prefer_free:
        candidates.sort(key=lambda p: (-1 if p.tier == ProviderTier.FREE else 0, -p.score))
    elif prefer_speed:
        candidates.sort(key=lambda p: -p.speed_toks_per_sec)
    else:
        candidates.sort(key=lambda p: -p.score)

    return candidates[0] if candidates else None
