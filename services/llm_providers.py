"""
LLM Provider implementations.

Each provider is an async callable:
  provider(prompt: str, max_tokens: int, temperature: float) -> str

Providers are tried in priority order by the LLM engine.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("llm_providers")


# ---------------------------------------------------------------------------
# Helper: unified HTTP call (aiohttp with urllib fallback)
# ---------------------------------------------------------------------------
async def _http_post_json(
    url: str,
    payload: dict,
    headers: dict | None = None,
    timeout: int = 60,
) -> dict:
    """POST JSON and return parsed response. Uses aiohttp if available."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, headers=headers or {}, timeout=timeout,
            ) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}: {text[:300]}")
                return json.loads(text)
    except ImportError:
        import urllib.request
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data,
            headers=headers or {"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())


async def _http_get_json(
    url: str,
    headers: dict | None = None,
    timeout: int = 30,
) -> dict:
    """GET and return parsed response."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers or {}, timeout=timeout,
            ) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}: {text[:300]}")
                return json.loads(text)
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())


DEFAULT_SYSTEM_PROMPT = (
    "You are a viral content creator for gaming/streaming clips. "
    "Always respond with valid JSON when requested."
)


def _build_chat_messages(prompt: str, system_prompt: str | None = None) -> list[dict]:
    messages = []
    sp = system_prompt or DEFAULT_SYSTEM_PROMPT
    messages.append({"role": "system", "content": sp})
    messages.append({"role": "user", "content": prompt})
    return messages


# ---------------------------------------------------------------------------
# OpenAI Provider (also works as base for OpenAI-compatible servers)
# ---------------------------------------------------------------------------
class OpenAIProvider:
    """OpenAI GPT provider. Also works with any OpenAI-compatible API
    (vLLM, LM Studio, LocalAI, Text Generation WebUI) via base_url."""

    def __init__(
        self,
        api_key: str = "sk-no-key",
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.openai.com").rstrip("/")

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": _build_chat_messages(prompt, system_prompt),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = await _http_post_json(url, payload, headers, timeout=60)
        return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Anthropic Claude Provider
# ---------------------------------------------------------------------------
class ClaudeProvider:
    """Anthropic Claude (Sonnet/Haiku) provider."""

    def __init__(self, api_key: str, model: str = "claude-3-haiku-20240307"):
        self.api_key = api_key
        self.model = model
        self.api_version = "2023-06-01"

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.api_version,
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt
        data = await _http_post_json(url, payload, headers, timeout=60)
        return data["content"][0]["text"].strip()


# ---------------------------------------------------------------------------
# Ollama (Local LLM) Provider
# ---------------------------------------------------------------------------
class OllamaProvider:
    """Local LLM via Ollama native API (non-OpenAI-compatible)."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1:8b"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        if system_prompt:
            payload["system"] = system_prompt
        data = await _http_post_json(f"{self.base_url}/api/generate", payload, timeout=120)
        return data.get("response", "").strip()


# ---------------------------------------------------------------------------
# vLLM Provider (OpenAI-compatible server)
# ---------------------------------------------------------------------------
class VLLMProvider:
    """vLLM — high-throughput local inference server.

    Exposes OpenAI-compatible /v1/chat/completions endpoint.
    Set VLLM_HOST (default http://localhost:8000) and VLLM_MODEL.
    """

    def __init__(self, base_url: str = "http://localhost:8000", model: str = "meta-llama/Llama-3-8B-Instruct"):
        self._openai = OpenAIProvider(api_key="sk-no-key", model=model, base_url=base_url)

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        return await self._openai(prompt, max_tokens, temperature, system_prompt)


# ---------------------------------------------------------------------------
# LM Studio Provider (OpenAI-compatible)
# ---------------------------------------------------------------------------
class LMStudioProvider:
    """LM Studio — local GUI for running LLMs.

    Exposes OpenAI-compatible API at http://localhost:1234/v1/.
    Set LM_STUDIO_MODEL (auto-detected if empty).
    """

    def __init__(self, base_url: str = "http://localhost:1234", model: str = "default"):
        self._openai = OpenAIProvider(api_key="lm-studio", model=model, base_url=base_url)

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        return await self._openai(prompt, max_tokens, temperature, system_prompt)


# ---------------------------------------------------------------------------
# LocalAI Provider (OpenAI-compatible)
# ---------------------------------------------------------------------------
class LocalAIProvider:
    """LocalAI — drop-in OpenAI-compatible local server.

    Supports GGUF, GPT4All, and many backends.
    Set LOCALAI_HOST (default http://localhost:8080) and LOCALAI_MODEL.
    """

    def __init__(self, base_url: str = "http://localhost:8080", model: str = "gpt-3.5-turbo"):
        self._openai = OpenAIProvider(api_key="local-ai", model=model, base_url=base_url)

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        return await self._openai(prompt, max_tokens, temperature, system_prompt)


# ---------------------------------------------------------------------------
# Text Generation WebUI (oobabooga) Provider (OpenAI-compatible)
# ---------------------------------------------------------------------------
class TextGenWebUIProvider:
    """Text Generation WebUI (oobabooga) — Gradio-based local LLM server.

    Exposes OpenAI-compatible API at http://localhost:5000/v1/.
    Set TEXTGEN_HOST and TEXTGEN_MODEL.
    """

    def __init__(self, base_url: str = "http://localhost:5000", model: str = "default"):
        self._openai = OpenAIProvider(api_key="text-gen", model=model, base_url=base_url)

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        return await self._openai(prompt, max_tokens, temperature, system_prompt)


# ---------------------------------------------------------------------------
# HuggingFace Inference API Provider
# ---------------------------------------------------------------------------
class HuggingFaceProvider:
    """HuggingFace Inference API — free tier available.

    Set HUGGINGFACE_API_TOKEN (optional for public models) and
    HUGGINGFACE_MODEL (default: HuggingFaceH4/zephyr-7b-beta).
    Free tier: 1000 requests/day, 30s timeout.
    """

    def __init__(
        self,
        api_token: str = "",
        model: str = "HuggingFaceH4/zephyr-7b-beta",
        base_url: str = "https://api-inference.huggingface.co",
    ):
        self.api_token = api_token
        self.model = model
        self.base_url = base_url.rstrip("/")

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        url = f"{self.base_url}/models/{self.model}"
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        # Build messages for chat-capable models
        messages = _build_chat_messages(prompt, system_prompt)

        # Try chat completion first (newer models)
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            data = await _http_post_json(
                f"{self.base_url}/models/{self.model}/v1/chat/completions",
                payload, headers, timeout=30,
            )
            return data["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

        # Fallback: text-generation pipeline
        full_prompt = f"{system_prompt or DEFAULT_SYSTEM_PROMPT}\n\n{prompt}"
        payload = {
            "inputs": full_prompt,
            "parameters": {
                "max_new_tokens": max_tokens,
                "temperature": max(temperature, 0.01),
                "return_full_text": False,
            },
        }
        data = await _http_post_json(url, payload, headers, timeout=30)

        if isinstance(data, list) and len(data) > 0:
            return data[0].get("generated_text", "").strip()
        if isinstance(data, dict) and "generated_text" in data:
            return data["generated_text"].strip()
        raise RuntimeError(f"HuggingFace unexpected response: {str(data)[:300]}")


# ---------------------------------------------------------------------------
# Google Gemini Provider
# ---------------------------------------------------------------------------
class GeminiProvider:
    """Google Gemini — free tier: 15 RPM, 1M tokens/day.

    Set GEMINI_API_KEY (get from https://aistudio.google.com/apikey).
    Default model: gemini-2.0-flash (fast, free).
    """

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self.model}:generateContent?key={self.api_key}"
        )
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will follow these instructions."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        data = await _http_post_json(url, payload, timeout=60)

        # Extract text from Gemini response
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text", "").strip()
        raise RuntimeError(f"Gemini empty response: {str(data)[:300]}")


# ---------------------------------------------------------------------------
# Mistral AI Provider
# ---------------------------------------------------------------------------
class MistralProvider:
    """Mistral AI — free tier available.

    Set MISTRAL_API_KEY (get from https://console.mistral.ai/).
    Default model: mistral-small-latest (fast, cheap).
    """

    def __init__(self, api_key: str, model: str = "mistral-small-latest"):
        self.api_key = api_key
        self.model = model

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        url = "https://api.mistral.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": _build_chat_messages(prompt, system_prompt),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = await _http_post_json(url, payload, headers, timeout=60)
        return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Groq Provider — En hızlı ücretsiz LLM API
# ---------------------------------------------------------------------------
class GroqProvider:
    """Groq API — Llama 3.1 70B/8B, Mixtral, Gemma2.

    ÜCRETSIZ: 14,400 req/gün, 6000 token/dak (Llama 3.1 70B).
    Saniyede 800+ token — en hızlı ücretsiz LLM API.
    Kayıt: https://console.groq.com
    Set GROQ_API_KEY.
    """

    MODELS = {
        "llama3-70b": "llama-3.1-70b-versatile",
        "llama3-8b": "llama-3.1-8b-instant",
        "mixtral": "mixtral-8x7b-32768",
        "gemma2": "gemma2-9b-it",
        "llama3-3b": "llama-3.2-3b-preview",
    }

    def __init__(self, api_key: str, model: str = "llama-3.1-70b-versatile"):
        self.api_key = api_key
        self.model = model

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": _build_chat_messages(prompt, system_prompt),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = await _http_post_json(url, payload, headers, timeout=30)
        return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Cohere Provider — Command-R, ücretsiz tier
# ---------------------------------------------------------------------------
class CohereProvider:
    """Cohere — Command-R, Command-R+ modelleri.

    ÜCRETSIZ: 1000 API çağrısı/ay (trial key).
    Kayıt: https://dashboard.cohere.com
    Set COHERE_API_KEY.
    """

    def __init__(self, api_key: str, model: str = "command-r"):
        self.api_key = api_key
        self.model = model

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        url = "https://api.cohere.com/v2/chat"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = await _http_post_json(url, payload, headers, timeout=60)
        return data["message"]["content"][0]["text"].strip()


# ---------------------------------------------------------------------------
# Together AI Provider — ücretsiz $25 başlangıç kredisi
# ---------------------------------------------------------------------------
class TogetherAIProvider:
    """Together AI — 200+ açık kaynak model.

    Kayıt: https://api.together.xyz (ücretsiz $25 kredi)
    Set TOGETHER_API_KEY.
    Önerilen ücretsiz modeller:
      - meta-llama/Llama-3.1-70B-Instruct-Turbo
      - mistralai/Mixtral-8x7B-Instruct-v0.1
      - google/gemma-2-9b-it
    """

    def __init__(
        self,
        api_key: str,
        model: str = "meta-llama/Llama-3.1-70B-Instruct-Turbo",
    ):
        self._openai = OpenAIProvider(
            api_key=api_key,
            model=model,
            base_url="https://api.together.xyz",
        )

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        return await self._openai(prompt, max_tokens, temperature, system_prompt)


# ---------------------------------------------------------------------------
# Cerebras Provider — Llama 3.1 70B, en hızlı inference
# ---------------------------------------------------------------------------
class CerebrasProvider:
    """Cerebras Inference — Llama 3.1 70B/8B.

    Ücretsiz tier: https://cloud.cerebras.ai
    Set CEREBRAS_API_KEY.
    Çok hızlı wafer-scale chip tabanlı inference.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "llama3.1-70b",
    ):
        self._openai = OpenAIProvider(
            api_key=api_key,
            model=model,
            base_url="https://api.cerebras.ai",
        )

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        return await self._openai(prompt, max_tokens, temperature, system_prompt)


# ---------------------------------------------------------------------------
# OpenRouter Provider — 50+ model gateway, birçoğu ücretsiz
# ---------------------------------------------------------------------------
class OpenRouterProvider:
    """OpenRouter — Unified API for 200+ LLMs.

    Ücretsiz modeller: google/gemma-2-9b-it:free, meta-llama/llama-3-8b:free, vb.
    Kayıt: https://openrouter.ai (ücretsiz tier mevcut)
    Set OPENROUTER_API_KEY.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "meta-llama/llama-3.1-8b-instruct:free",
        site_url: str = "https://github.com/Tuncay-klip",
    ):
        self.api_key = api_key
        self.model = model
        self.site_url = site_url

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": self.site_url,
            "X-Title": "Tuncay-Klip",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": _build_chat_messages(prompt, system_prompt),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = await _http_post_json(url, payload, headers, timeout=60)
        return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Nvidia NIM Provider — Nemotron, Llama, ücretsiz tier
# ---------------------------------------------------------------------------
class NvidiaProvider:
    """Nvidia NIM Inference — Nemotron-4-340B, Llama 3.1.

    Kayıt: https://build.nvidia.com (ücretsiz 1000 token kredi)
    Set NVIDIA_API_KEY.
    En iyi modeller: nvidia/nemotron-4-340b-instruct, meta/llama-3.1-70b-instruct.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "meta/llama-3.1-70b-instruct",
    ):
        self._openai = OpenAIProvider(
            api_key=api_key,
            model=model,
            base_url="https://integrate.api.nvidia.com",
        )

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        return await self._openai(prompt, max_tokens, temperature, system_prompt)


# ---------------------------------------------------------------------------
# Template Fallback Provider (zero dependency)
# ---------------------------------------------------------------------------
class TemplateProvider:
    """Rules-based fallback provider. Always works, no API needed."""

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7
    ) -> str:
        from src.ai_generator import ai_title_generator

        streamer = self._extract(prompt, "Streamer:", "Tuncay")
        category = self._extract(prompt, "Category:", "exciting")
        emotion = self._extract(prompt, "Emotion:", "exciting")
        platform = self._extract(prompt, "Platform:", "youtube")
        game = self._extract(prompt, "Game:", "Various")

        if "title" in prompt.lower() and "example format" in prompt.lower():
            titles = [
                ai_title_generator.generate_title(emotion=emotion, category=category, streamer_name=streamer),
                ai_title_generator.generate_title(emotion=emotion, category=category, streamer_name=streamer),
                ai_title_generator.generate_title(emotion=emotion, category=category, streamer_name=streamer),
            ]
            return json.dumps(titles)

        elif "description" in prompt.lower() and "paragraphs" in prompt.lower():
            return ai_title_generator.generate_description(
                title=f"{streamer} - {category} moment",
                streamer_name=streamer,
                category=category,
                emotion=emotion,
            )

        elif "hashtag" in prompt.lower():
            tags = ai_title_generator.generate_hashtags(
                category=category, platform=platform,
                game_name=game, streamer_name=streamer,
            )
            return json.dumps(tags)

        elif "virality_score" in prompt:
            return json.dumps({
                "summary": f"Exciting {category} moment from {streamer}",
                "mood": category,
                "virality_score": 7,
                "best_platforms": ["youtube", "tiktok"],
                "target_audience": "Gaming enthusiasts, 18-34",
                "suggested_title": ai_title_generator.generate_title(
                    emotion=emotion, category=category, streamer_name=streamer,
                ),
                "key_moments_described": "Highlight moment with emotional peak",
                "improvement_suggestions": "Add subtitles, zoom on reaction",
            })

        return ai_title_generator.generate_title(
            emotion=emotion, streamer_name=streamer, category=category,
        )

    @staticmethod
    def _extract(text: str, key: str, default: str = "") -> str:
        for line in text.split("\n"):
            if key.lower() in line.lower():
                parts = line.split(":", 1)
                if len(parts) > 1:
                    return parts[1].strip().rstrip(",")
        return default
