"""
LLM Provider implementations.

Each provider is an async callable:
  provider(prompt: str, max_tokens: int, temperature: float) -> str
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("llm_providers")


# ---------------------------------------------------------------------------
# OpenAI Provider
# ---------------------------------------------------------------------------
class OpenAIProvider:
    """OpenAI GPT-4o / GPT-4o-mini provider."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model
        self._http_client = None

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7
    ) -> str:
        try:
            import aiohttp
        except ImportError:
            return await self._sync_call(prompt, max_tokens, temperature)

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a viral content creator for gaming/streaming clips. Always respond with valid JSON when requested."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=30) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"OpenAI API error {resp.status}: {text[:200]}")
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()

    async def _sync_call(
        self, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        """Fallback sync call when aiohttp unavailable."""
        import urllib.request
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a viral content creator for gaming/streaming clips. Always respond with valid JSON when requested."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
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
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7
    ) -> str:
        try:
            import aiohttp
        except ImportError:
            return await self._sync_call(prompt, max_tokens, temperature)

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.api_version,
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "user", "content": prompt},
            ],
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=30) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Claude API error {resp.status}: {text[:200]}")
                data = await resp.json()
                return data["content"][0]["text"].strip()

    async def _sync_call(
        self, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        import urllib.request
        payload = json.dumps({
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": self.api_version,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["content"][0]["text"].strip()


# ---------------------------------------------------------------------------
# Ollama (Local LLM) Provider
# ---------------------------------------------------------------------------
class OllamaProvider:
    """Local LLM via Ollama API."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1:8b"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7
    ) -> str:
        try:
            import aiohttp
        except ImportError:
            return await self._sync_call(prompt, max_tokens, temperature)

        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=60) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Ollama error {resp.status}: {text[:200]}")
                data = await resp.json()
                return data.get("response", "").strip()

    async def _sync_call(
        self, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        import urllib.request
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip()


# ---------------------------------------------------------------------------
# Template Fallback Provider (zero dependency)
# ---------------------------------------------------------------------------
class TemplateProvider:
    """Rules-based fallback provider. Always works, no API needed."""

    async def __call__(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7
    ) -> str:
        from src.ai_generator import ai_title_generator

        # Extract context from prompt heuristically
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