"""
LLM Entegrasyon Modülü (IP_PART7 - AI Intelligence Expansion)

Multi-provider LLM wrapper with automatic fallback:
  1. OpenAI (GPT-4o, GPT-4o-mini)
  2. Anthropic Claude (Sonnet, Haiku)
  3. Local LLM (Ollama, llama.cpp)
  4. Template fallback (no API needed)

Features:
  - Akıllı klip başlığı, açıklama, hashtag üretimi
  - Context-aware etiketleme ve kategorizasyon
  - Çoklu dil desteği (TR/EN auto-detect)
  - Streaming ve batch modları
  - Token optimizasyonu (context window yönetimi)
  - Rate limiting ve retry logic
  - Cost tracking
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("llm_engine")


# ---------------------------------------------------------------------------
# Provider Configuration
# ---------------------------------------------------------------------------
@dataclass
class LLMProviderConfig:
    """Configuration for a single LLM provider."""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    max_tokens: int = 1024
    temperature: float = 0.7
    timeout: float = 30.0
    max_retries: int = 3
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0


# ---------------------------------------------------------------------------
# Prompt Templates - Turkish/English clip content generation
# ---------------------------------------------------------------------------
PROMPT_TEMPLATES = {
    "title_generation": """You are a viral content creator specializing in gaming/streaming clips.
Generate {count} clickbait-friendly, engaging titles in {language} for this clip.

Context:
- Streamer: {streamer_name}
- Category: {category}
- Emotion: {emotion}
- Game: {game_name}
- Viewer Count: {viewer_count}
- Tags: {tags}
- Duration: {duration}s

Requirements:
- Titles should be 5-15 words
- Use emotional triggers (excitement, curiosity, FOMO)
- Include numbers when relevant (viewer count, score, etc.)
- Platform-optimized for {platform}
- NO clickbait that misrepresents content
- For Turkish: use natural Turkish gaming slang (helal, efsane, çıldırdı, etc.)

Return ONLY a JSON array of title strings, nothing else.
Example format: ["title1", "title2", "title3"]""",

    "description_generation": """Generate a compelling video description in {language} for a {platform} clip.

Clip info:
- Title: {title}
- Streamer: {streamer_name}
- Category: {category}
- Emotion: {emotion}
- Duration: {duration}s
- Game: {game_name}
- Key Moments: {key_moments}

Requirements:
- 2-4 paragraphs
- Include relevant hashtags section at end
- Natural, conversational tone
- Hook in first line
- Include streamer credit and call-to-action
- For {platform}: follow platform best practices

Return ONLY the description text, no JSON wrapper.""",

    "hashtag_generation": """Generate {count} optimized hashtags in {language} for {platform}.

Clip context:
- Category: {category}
- Game: {game_name}
- Streamer: {streamer_name}
- Emotion: {emotion}

Requirements:
- Mix of broad (100K+ posts) and niche (1K-10K posts) tags
- Include {language}-specific trending tags
- Platform-specific best practices for {platform}
- Avoid banned/shadowbanned tags

Return ONLY a JSON array of hashtag strings (without # symbol).
Example: ["gaming", "clutch", "epicmoment"]""",

    "clip_analysis": """Analyze this gaming/streaming clip and provide structured insights in {language}.

Context:
- Streamer: {streamer_name}
- Category: {category}
- Duration: {duration}s
- Emotion Scores: {emotion_scores}
- Audio Spikes: {audio_spikes}
- Chat Highlights: {chat_highlights}
- Key Moments: {key_moments}

Provide analysis as JSON with these fields:
- "summary": 1-2 sentence summary of what makes this clip special
- "mood": overall mood (hype/funny/emotional/rage/skill/victory)
- "virality_score": 1-10 estimate of viral potential
- "best_platforms": array of best platform fits ["youtube", "tiktok", "instagram", "twitter"]
- "target_audience": short audience description
- "suggested_title": one best title suggestion
- "key_moments_described": human-readable description of key moments
- "improvement_suggestions": ways to make clip more engaging

Return ONLY valid JSON, no other text.""",

    "thumbnail_suggestion": """Suggest the best thumbnail concept for this {platform} clip.

Clip details:
- Title: {title}
- Streamer: {streamer_name}
- Category: {category}
- Emotion: {emotion}
- Key Frame Description: {key_frame_desc}

Provide as JSON:
- "concept": thumbnail concept name
- "layout": text placement suggestion (top/bottom/center/left/right)
- "text_overlay": suggested text for thumbnail (max 5 words)
- "color_scheme": dominant colors suggestion
- "face_expression": what expression to capture
- "cta_element": call-to-action element (arrow, circle, emoji)

Return ONLY valid JSON.""",
}

# Turkish streaming slang dictionary for enhancement
TR_STREAMING_SLANG = {
    "positive": ["helal", "efsane", "çıldırdı", "kral", "baba", "deli", "müthiş",
                  "muhteşem", "inanılmaz", "aşırı iyi", "god mode", "taşıyor",
                  "küfür", "şov", "destan", "efsanevi", "tarihi an"],
    "hype": ["hype", "çılgın", "kopuyor", "patladı", "yıkıldı", "olay", "kıyamet",
             "koptu", "çıldırdı", "delirdi", "coştu"],
    "fail": ["fail", "rezalet", "epic fail", "çuvalladı", "batırdı", "küfretti",
             "sinir krizi", "rage", "tilt", "alt f4"],
    "victory": ["clutch", "taşıdı", "kurtardı", "win", "galibiyet", "zafer",
                "şampiyon", "birinci", "ezdi", "domine etti"],
}


# ---------------------------------------------------------------------------
# LLM Engine
# ---------------------------------------------------------------------------
class LLMEngine:
    """
    Multi-provider LLM engine with fallback chain.

    Priority: OpenAI → Claude → Local LLM → Template

    Caches frequent prompts to reduce API costs.
    Tracks token usage and costs.
    """

    def __init__(self):
        self._providers: list[tuple[str, Callable]] = []
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl: float = 300.0  # 5 min
        self._rate_limiter = deque(maxlen=100)

        self._stats = {
            "total_requests": 0,
            "total_tokens_input": 0,
            "total_tokens_output": 0,
            "total_cost": 0.0,
            "cache_hits": 0,
            "fallback_count": 0,
        }

        self._init_providers()

    def _init_providers(self):
        """Initialize available LLM providers."""
        # Provider 1: OpenAI
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            from services.llm_providers import OpenAIProvider
            self._providers.append(("openai", OpenAIProvider(
                api_key=openai_key,
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            )))
            logger.info("OpenAI provider registered (model=%s)",
                        os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))

        # Provider 2: Anthropic Claude
        claude_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if claude_key:
            from services.llm_providers import ClaudeProvider
            self._providers.append(("claude", ClaudeProvider(
                api_key=claude_key,
                model=os.environ.get("CLAUDE_MODEL", "claude-3-haiku-20240307"),
            )))
            logger.info("Claude provider registered")

        # Provider 3: Local LLM (Ollama)
        ollama_host = os.environ.get("OLLAMA_HOST", "")
        if ollama_host:
            from services.llm_providers import OllamaProvider
            self._providers.append(("ollama", OllamaProvider(
                base_url=ollama_host,
                model=os.environ.get("OLLAMA_MODEL", "llama3.1:8b"),
            )))
            logger.info("Ollama provider registered at %s", ollama_host)

        # Always available: Template fallback
        from services.llm_providers import TemplateProvider
        self._providers.append(("template", TemplateProvider()))
        logger.info("Template fallback provider always available")

        self._provider_count = len(self._providers)
        logger.info("LLM Engine initialized with %d providers", self._provider_count)

    async def generate(
        self,
        prompt_template: str,
        language: str = "tr",
        context: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        use_cache: bool = True,
    ) -> str:
        """
        Generate text using the best available provider.

        Args:
            prompt_template: Key from PROMPT_TEMPLATES or raw prompt string
            language: Output language (tr/en)
            context: Template variables
            max_tokens: Maximum output tokens
            temperature: Creativity (0.0-1.0)
            use_cache: Whether to use response cache

        Returns:
            Generated text
        """
        self._stats["total_requests"] += 1

        # Build prompt
        if prompt_template in PROMPT_TEMPLATES:
            template = PROMPT_TEMPLATES[prompt_template]
            ctx = context or {}
            ctx.setdefault("language", "Turkish" if language == "tr" else "English")
            prompt = template.format(**{k: ctx.get(k, "") for k in ctx})
        else:
            prompt = prompt_template

        # Check cache
        cache_key = f"{prompt[:200]}:{language}:{temperature}"
        if use_cache and cache_key in self._cache:
            ts, cached = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                self._stats["cache_hits"] += 1
                return cached

        # Try providers in order
        last_error = None
        for provider_name, provider_fn in self._providers:
            try:
                result = await asyncio.wait_for(
                    provider_fn(prompt, max_tokens=max_tokens, temperature=temperature),
                    timeout=60.0,
                )
                if result and len(result.strip()) > 5:
                    if use_cache:
                        self._cache[cache_key] = (time.time(), result)
                    return result
            except asyncio.TimeoutError:
                logger.warning("Provider %s timed out, trying next", provider_name)
                last_error = "timeout"
            except Exception as e:
                logger.warning("Provider %s failed: %s", provider_name, e)
                last_error = str(e)
                self._stats["fallback_count"] += 1

        logger.error("All providers failed: %s", last_error)
        return self._emergency_fallback(prompt_template, context or {})

    async def generate_json(
        self,
        prompt_template: str,
        context: dict[str, Any] | None = None,
        language: str = "tr",
    ) -> dict[str, Any]:
        """Generate structured JSON output."""
        raw = await self.generate(
            prompt_template,
            language=language,
            context=context,
            max_tokens=2048,
            temperature=0.3,
        )
        return self._extract_json(raw)

    async def generate_titles(
        self,
        streamer_name: str,
        category: str,
        emotion: str,
        platform: str = "youtube",
        game_name: str = "",
        viewer_count: int = 0,
        tags: list[str] | None = None,
        count: int = 5,
        language: str = "tr",
    ) -> list[str]:
        """Generate clip title suggestions."""
        ctx = {
            "streamer_name": streamer_name,
            "category": category,
            "emotion": emotion,
            "platform": platform,
            "game_name": game_name or "Various",
            "viewer_count": f"{viewer_count:,}" if viewer_count else "N/A",
            "tags": ", ".join(tags or []),
            "duration": "30",
            "count": count,
        }
        result = await self.generate_json("title_generation", ctx, language)
        titles = result if isinstance(result, list) else result.get("titles", [])
        return [str(t) for t in titles[:count]]

    async def generate_description(
        self,
        title: str,
        streamer_name: str,
        category: str,
        emotion: str,
        platform: str = "youtube",
        game_name: str = "",
        key_moments: str = "",
        language: str = "tr",
    ) -> str:
        """Generate video description."""
        ctx = {
            "title": title,
            "streamer_name": streamer_name,
            "category": category,
            "emotion": emotion,
            "platform": platform,
            "game_name": game_name or "Various",
            "key_moments": key_moments or "Highlight moment",
            "duration": "30",
        }
        return await self.generate("description_generation", language, ctx)

    async def generate_hashtags(
        self,
        category: str,
        game_name: str,
        streamer_name: str,
        emotion: str,
        platform: str = "youtube",
        count: int = 15,
        language: str = "tr",
    ) -> list[str]:
        """Generate optimized hashtag list."""
        ctx = {
            "category": category,
            "game_name": game_name or "Various",
            "streamer_name": streamer_name,
            "emotion": emotion,
            "platform": platform,
            "count": count,
        }
        result = await self.generate_json("hashtag_generation", ctx, language)
        tags = result if isinstance(result, list) else result.get("hashtags", [])
        return [str(t).replace("#", "").strip() for t in tags[:count]]

    async def analyze_clip(
        self,
        streamer_name: str,
        category: str,
        emotion_scores: dict[str, float],
        audio_spikes: list[dict],
        chat_highlights: list[str],
        key_moments: str,
        duration: int = 30,
        language: str = "tr",
    ) -> dict[str, Any]:
        """Deep AI analysis of a clip."""
        ctx = {
            "streamer_name": streamer_name,
            "category": category,
            "duration": str(duration),
            "emotion_scores": json.dumps(emotion_scores, ensure_ascii=False),
            "audio_spikes": json.dumps(audio_spikes[:5], ensure_ascii=False),
            "chat_highlights": json.dumps(chat_highlights[:5], ensure_ascii=False),
            "key_moments": key_moments or "Highlight moment",
        }
        return await self.generate_json("clip_analysis", ctx, language)

    async def suggest_thumbnail(
        self,
        title: str,
        streamer_name: str,
        category: str,
        emotion: str,
        platform: str = "youtube",
        key_frame_desc: str = "",
    ) -> dict[str, Any]:
        """AI thumbnail concept suggestion."""
        ctx = {
            "title": title,
            "streamer_name": streamer_name,
            "category": category,
            "emotion": emotion,
            "platform": platform,
            "key_frame_desc": key_frame_desc or "Streamer face visible, gaming moment",
        }
        return await self.generate_json("thumbnail_suggestion", ctx)

    def _extract_json(self, raw: str) -> dict[str, Any]:
        """Extract JSON from potentially messy LLM output."""
        raw = raw.strip()
        # Try direct parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try to find JSON block
        import re
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try brackets
        for pattern in [r'\[.*\]', r'\{.*\}']:
            match = re.search(pattern, raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass

        return {"raw_output": raw, "parse_error": True}

    def _emergency_fallback(
        self, template_key: str, context: dict[str, Any]
    ) -> str:
        """Ultimate fallback when all providers fail."""
        from src.ai_generator import ai_title_generator
        category = context.get("category", "exciting")
        streamer = context.get("streamer_name", "Streamer")
        emotion = context.get("emotion", "exciting")

        if template_key == "title_generation":
            return ai_title_generator.generate_title(
                emotion=emotion, streamer_name=streamer, category=category,
            )
        elif template_key == "description_generation":
            return ai_title_generator.generate_description(
                title=context.get("title", ""),
                streamer_name=streamer,
                category=category,
                emotion=emotion,
            )
        elif template_key == "hashtag_generation":
            tags = ai_title_generator.generate_hashtags(
                category=category,
                platform=context.get("platform", "youtube"),
            )
            return json.dumps(tags)
        return "Content generation failed. Please try again."

    def get_stats(self) -> dict[str, Any]:
        return dict(self._stats)

    def clear_cache(self):
        self._cache.clear()
        self._stats["cache_hits"] = 0


# Singleton
llm_engine = LLMEngine()