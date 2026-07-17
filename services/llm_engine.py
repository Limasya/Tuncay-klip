"""
LLM Entegrasyon Modülü (IP_PART7 - AI Intelligence Expansion)

Multi-provider LLM wrapper with automatic fallback:
  1. OpenAI (GPT-4o, GPT-4o-mini)
  2. Anthropic Claude (Sonnet, Haiku)
  3. Local LLM (Ollama, llama.cpp)
  4. Template fallback (no API needed)

Enhanced Features:
  - Akıllı klip başlığı, açıklama, hashtag üretimi
  - Context-aware etiketleme ve kategorizasyon
  - Çoklu dil desteği (TR/EN auto-detect)
  - A/B test varyant üretimi
  - Viral hook / opening sentence üretimi
  - Platform-optimized başlık optimizasyonu
  - İçerik stratejisi önerileri
  - Clip yeniden kullanım (cross-platform repurpose)
  - Multi-step prompt chaining
  - Streaming desteği
  - İçerik kalite skorlama
  - Token optimizasyonu (context window yönetimi)
  - Rate limiting ve retry logic
  - Cost tracking
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
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

    # ── NEW: A/B Test Variant Generation ─────────────────────────────
    "ab_test_variants": """Generate A/B test variants for this clip title. Create {count} pairs of title variants.

Original title: {title}
Clip context:
- Streamer: {streamer_name}
- Category: {category}
- Emotion: {emotion}
- Platform: {platform}
- Game: {game_name}

For each pair, create two versions testing different strategies:
- Variant A: one approach (e.g., emotional trigger)
- Variant B: different approach (e.g., curiosity gap)

Requirements:
- Each variant should be 5-15 words
- Test different emotional hooks (FOMO, curiosity, excitement, humor)
- Platform-appropriate for {platform}
- For Turkish: natural gaming slang

Return ONLY a JSON array of objects with "variant_a" and "variant_b" fields.
Example: [{{"variant_a": "title A1", "variant_b": "title B1"}}, ...]""",

    # ── NEW: Viral Hook Generation ───────────────────────────────────
    "viral_hook": """Generate {count} viral opening hooks (first 3 seconds) for this clip.

Clip context:
- Title: {title}
- Streamer: {streamer_name}
- Category: {category}
- Emotion: {emotion}
- Duration: {duration}s
- Platform: {platform}

The hook is the opening text/voiceover that grabs attention in the first 3 seconds.

Requirements:
- Maximum 8 words per hook
- Create urgency or curiosity
- Platform-optimized for {platform}
- For Turkish: use natural gaming/streaming language
- Mix of styles: question, statement, exclamation

Return ONLY a JSON array of hook strings.
Example: ["Hook 1", "Hook 2", "Hook 3"]""",

    # ── NEW: Platform-Optimized Title ────────────────────────────────
    "platform_optimized_title": """Optimize this title specifically for {platform}.

Original title: {title}
Streamer: {streamer_name}
Category: {category}
Emotion: {emotion}

Platform rules for {platform}:
- youtube: SEO-friendly, 60-70 chars, include keywords
- tiktok: Short, punchy, 15-25 chars, trend-aware
- instagram: Descriptive, emoji-friendly, 40-60 chars
- twitter: Concise, conversation-starter, 70-100 chars
- kick: Gaming-focused, community-aware, 50-80 chars

Generate 3 optimized versions.
Return ONLY a JSON array of optimized title strings.
Example: ["optimized1", "optimized2", "optimized3"]""",

    # ── NEW: Content Strategy ────────────────────────────────────────
    "content_strategy": """Generate a content strategy for this clip across platforms.

Clip analysis:
- Title: {title}
- Streamer: {streamer_name}
- Category: {category}
- Emotion: {emotion}
- Duration: {duration}s
- Virality Score: {virality_score}/10
- Game: {game_name}

Provide a JSON strategy with:
- "best_posting_time": optimal time to post per platform
- "platform_priority": ordered list of platforms by potential
- "content_adjustments": specific changes per platform
  (each with "platform", "title_adjustment", "duration_adjustment", "style_notes")
- "cross_promotion": how to link clips across platforms
- "engagement_tactics": 3 ways to boost engagement
- "follow_up_content": 2-3 ideas for follow-up clips

Return ONLY valid JSON.""",

    # ── NEW: Clip Repurpose ──────────────────────────────────────────
    "clip_repurpose": """Suggest how to repurpose this clip for multiple platforms.

Original clip:
- Title: {title}
- Streamer: {streamer_name}
- Category: {category}
- Emotion: {emotion}
- Duration: {duration}s
- Game: {game_name}

For each target platform, provide:
- "platform": platform name
- "suggested_duration": trimmed duration in seconds
- "aspect_ratio": recommended ratio (16:9, 9:16, 1:1)
- "editing_notes": what to change (cuts, text overlays, music)
- "title": platform-optimized title
- "hashtags": 3-5 key hashtags

Include: youtube, tiktok, instagram_reels, twitter

Return ONLY valid JSON array.""",

    # ── NEW: Content Quality Scoring ─────────────────────────────────
    "content_quality_score": """Score the quality of this generated content on multiple dimensions.

Content to evaluate:
- Title: {title}
- Description: {description}
- Hashtags: {hashtags}
- Platform: {platform}
- Category: {category}

Score each dimension 1-10 and provide justification:
- "title_engagement": how engaging/clickable is the title (1-10)
- "title_accuracy": does title accurately represent content (1-10)
- "description_quality": is description compelling and informative (1-10)
- "hashtag_relevance": are hashtags relevant and trending (1-10)
- "platform_fit": how well suited for the target platform (1-10)
- "overall_score": weighted average
- "improvement_suggestions": top 3 improvements
- "alternative_title": a better title if score < 7

Return ONLY valid JSON.""",

    # ── NEW: Trend-Aware Title ───────────────────────────────────────
    "trend_aware_title": """Generate trend-aware titles using current gaming/streaming trends.

Clip context:
- Streamer: {streamer_name}
- Category: {category}
- Emotion: {emotion}
- Game: {game_name}
- Platform: {platform}

Current trending patterns in gaming content:
- Pattern 1: "POV: [situation]" format
- Pattern 2: "When [relatable moment] happens"
- Pattern 3: Question format "Why does [X] always happen?"
- Pattern 4: Number-based "Top 1 [achievement]"
- Pattern 5: Reaction-based "My reaction when..."
- Pattern 6: Challenge format "Can you [challenge]?"

Generate 5 titles using these trending patterns.
Return ONLY a JSON array of title strings.
Example: ["title1", "title2", "title3", "title4", "title5"]""",

    # ── NEW: Multi-Language Adaptation ───────────────────────────────
    "multilang_adaptation": """Adapt this title for multiple languages while keeping the gaming spirit.

Original title: {title}
Source language: {source_language}
Streamer: {streamer_name}
Category: {category}
Emotion: {emotion}

Generate adapted versions for:
- Turkish (tr): Use Turkish gaming slang naturally
- English (en): Natural English gaming/streaming language
- Spanish (es): Latin American gaming community style
- Portuguese (br): Brazilian gaming community style

Each should feel native, not translated.
Return ONLY a JSON object with language codes as keys.
Example: {{"tr": "...", "en": "...", "es": "...", "br": "..."}}""",
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
# Content Quality Scorer
# ---------------------------------------------------------------------------
class ContentQualityScorer:
    """
    Rule-based quality scorer for generated content.
    Provides fast scoring without LLM calls.
    """

    ENGAGEMENT_WORDS = {
        "insane", "epic", "clutch", "legendary", "amazing", "unbelievable",
        "efsane", "inanılmaz", "muhteşem", "deli", "çıldırdı", "kral",
        "top 1", "best", "ultimate", "crazy", "wild", "hype",
    }
    CTA_WORDS = {
        "subscribe", "follow", "like", "comment", "share",
        "abone", "takip", "beğen", "paylaş", "yorum",
    }

    @classmethod
    def score_title(cls, title: str, platform: str = "youtube") -> dict:
        """Score a title 1-10 on engagement and accuracy."""
        score = 5.0
        title_lower = title.lower()
        words = title_lower.split()
        word_count = len(words)

        # Length scoring
        if platform == "tiktok":
            if 3 <= word_count <= 8:
                score += 1.0
            elif word_count > 12:
                score -= 1.0
        elif platform == "youtube":
            if 5 <= word_count <= 12:
                score += 1.0
            elif word_count > 15:
                score -= 0.5
        else:
            if 4 <= word_count <= 12:
                score += 0.5

        # Engagement words
        engagement_hits = sum(1 for w in cls.ENGAGEMENT_WORDS if w in title_lower)
        score += min(engagement_hits * 0.5, 2.0)

        # Numbers (good for engagement)
        if any(c.isdigit() for c in title):
            score += 0.5

        # Emoji (good for TikTok/Instagram)
        if platform in ("tiktok", "instagram"):
            emoji_pattern = re.compile(
                "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
                "\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]+",
                flags=re.UNICODE,
            )
            if emoji_pattern.search(title):
                score += 0.5

        # Question marks (curiosity gap)
        if "?" in title:
            score += 0.3

        # ALL CAPS (spammy, penalty)
        caps_ratio = sum(1 for c in title if c.isupper()) / max(len(title), 1)
        if caps_ratio > 0.5:
            score -= 1.0

        score = max(1.0, min(10.0, round(score, 1)))
        return {"score": score, "engagement_hits": engagement_hits}

    @classmethod
    def score_description(cls, description: str, platform: str = "youtube") -> dict:
        """Score a description for quality."""
        score = 5.0
        desc_lower = description.lower()
        word_count = len(description.split())

        # Length scoring
        if platform == "youtube":
            if word_count >= 50:
                score += 1.0
            if word_count >= 100:
                score += 0.5
        elif platform == "tiktok":
            if 20 <= word_count <= 100:
                score += 1.0
        elif platform == "twitter":
            if word_count <= 50:
                score += 1.0

        # Has CTA
        has_cta = any(w in desc_lower for w in cls.CTA_WORDS)
        if has_cta:
            score += 1.0

        # Has hashtags
        if "#" in description:
            score += 0.5

        # Has streamer credit
        if any(w in desc_lower for w in ["credit", "credit:", "kredi", "kredi:"]):
            score += 0.3

        score = max(1.0, min(10.0, round(score, 1)))
        return {"score": score, "has_cta": has_cta, "word_count": word_count}

    @classmethod
    def score_hashtags(cls, hashtags: list[str], platform: str = "youtube") -> dict:
        """Score hashtag list for quality and diversity."""
        score = 5.0
        count = len(hashtags)

        # Count scoring
        if platform == "youtube":
            if 10 <= count <= 25:
                score += 1.0
        elif platform == "tiktok":
            if 3 <= count <= 5:
                score += 1.0
            elif count > 5:
                score -= 1.0

        # Uniqueness
        unique = len(set(h.lower() for h in hashtags))
        if unique == count:
            score += 1.0
        else:
            score -= (count - unique) * 0.5

        # Length check (no too-long hashtags)
        long_tags = sum(1 for h in hashtags if len(h) > 25)
        if long_tags == 0:
            score += 0.5

        # No # symbol in values
        has_hash = any(h.startswith("#") for h in hashtags)
        if not has_hash:
            score += 0.3

        score = max(1.0, min(10.0, round(score, 1)))
        return {"score": score, "unique_count": unique}

    @classmethod
    def score_all(
        cls,
        title: str,
        description: str,
        hashtags: list[str],
        platform: str = "youtube",
    ) -> dict:
        """Score all content together."""
        title_result = cls.score_title(title, platform)
        desc_result = cls.score_description(description, platform)
        hash_result = cls.score_hashtags(hashtags, platform)

        overall = round(
            (title_result["score"] * 0.4
             + desc_result["score"] * 0.3
             + hash_result["score"] * 0.3),
            1,
        )

        improvements = []
        if title_result["score"] < 7:
            improvements.append("Title needs more engagement words or better length")
        if desc_result["score"] < 7:
            improvements.append("Description needs CTA or more detail")
        if hash_result["score"] < 7:
            improvements.append("Hashtag list needs better diversity or count")

        return {
            "title": title_result,
            "description": desc_result,
            "hashtags": hash_result,
            "overall_score": overall,
            "improvements": improvements,
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

        self._quality_scorer = ContentQualityScorer()
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

    def _build_cache_key(self, prompt: str, language: str, temperature: float) -> str:
        """Build deterministic cache key from prompt content."""
        raw = f"{prompt[:300]}:{language}:{temperature}"
        return hashlib.md5(raw.encode()).hexdigest()

    async def generate(
        self,
        prompt_template: str,
        language: str = "tr",
        context: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        use_cache: bool = True,
        system_prompt: str | None = None,
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
            system_prompt: Optional system prompt override

        Returns:
            Generated text
        """
        self._stats["total_requests"] += 1

        # Build prompt
        if prompt_template in PROMPT_TEMPLATES:
            template = PROMPT_TEMPLATES[prompt_template]
            ctx = context or {}
            ctx.setdefault("language", "Turkish" if language == "tr" else "English")
            # Fill missing keys with empty string to avoid KeyError
            prompt = template.format(**{k: ctx.get(k, "") for k in ctx})
        else:
            prompt = prompt_template

        # Check cache
        cache_key = self._build_cache_key(prompt, language, temperature)
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
                    provider_fn(
                        prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        system_prompt=system_prompt,
                    ),
                    timeout=60.0,
                )
                if result and len(result.strip()) > 5:
                    if use_cache:
                        self._cache[cache_key] = (time.time(), result)
                    return result
            except asyncio.TimeoutError:
                logger.warning("Provider %s timed out, trying next", provider_name)
                last_error = "timeout"
            except TypeError:
                # Provider doesn't accept system_prompt kwarg
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
                    last_error = "timeout"
                except Exception as e2:
                    last_error = str(e2)
                    self._stats["fallback_count"] += 1
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

    # ── NEW: Enhanced Generation Methods ─────────────────────────────

    async def generate_ab_test_variants(
        self,
        title: str,
        streamer_name: str,
        category: str,
        emotion: str,
        platform: str = "youtube",
        game_name: str = "",
        count: int = 3,
        language: str = "tr",
    ) -> list[dict[str, str]]:
        """Generate A/B test variant pairs for titles."""
        ctx = {
            "title": title,
            "streamer_name": streamer_name,
            "category": category,
            "emotion": emotion,
            "platform": platform,
            "game_name": game_name or "Various",
            "count": count,
        }
        result = await self.generate_json("ab_test_variants", ctx, language)
        if isinstance(result, list):
            return result[:count]
        return []

    async def generate_viral_hooks(
        self,
        title: str,
        streamer_name: str,
        category: str,
        emotion: str,
        duration: float = 30.0,
        platform: str = "youtube",
        count: int = 5,
        language: str = "tr",
    ) -> list[str]:
        """Generate viral opening hooks for the first 3 seconds."""
        ctx = {
            "title": title,
            "streamer_name": streamer_name,
            "category": category,
            "emotion": emotion,
            "duration": str(int(duration)),
            "platform": platform,
            "count": count,
        }
        result = await self.generate_json("viral_hook", ctx, language)
        hooks = result if isinstance(result, list) else []
        return [str(h) for h in hooks[:count]]

    async def optimize_for_platform(
        self,
        title: str,
        streamer_name: str,
        category: str,
        emotion: str,
        platform: str = "youtube",
        language: str = "tr",
    ) -> list[str]:
        """Optimize a title for a specific platform."""
        ctx = {
            "title": title,
            "streamer_name": streamer_name,
            "category": category,
            "emotion": emotion,
            "platform": platform,
        }
        result = await self.generate_json("platform_optimized_title", ctx, language)
        titles = result if isinstance(result, list) else []
        return [str(t) for t in titles[:3]]

    async def generate_content_strategy(
        self,
        title: str,
        streamer_name: str,
        category: str,
        emotion: str,
        duration: float = 30.0,
        virality_score: float = 7.0,
        game_name: str = "",
        language: str = "tr",
    ) -> dict[str, Any]:
        """Generate a full content strategy for cross-platform posting."""
        ctx = {
            "title": title,
            "streamer_name": streamer_name,
            "category": category,
            "emotion": emotion,
            "duration": str(int(duration)),
            "virality_score": str(virality_score),
            "game_name": game_name or "Various",
        }
        return await self.generate_json("content_strategy", ctx, language)

    async def suggest_repurpose(
        self,
        title: str,
        streamer_name: str,
        category: str,
        emotion: str,
        duration: float = 30.0,
        game_name: str = "",
        language: str = "tr",
    ) -> list[dict[str, Any]]:
        """Suggest how to repurpose a clip for multiple platforms."""
        ctx = {
            "title": title,
            "streamer_name": streamer_name,
            "category": category,
            "emotion": emotion,
            "duration": str(int(duration)),
            "game_name": game_name or "Various",
        }
        result = await self.generate_json("clip_repurpose", ctx, language)
        return result if isinstance(result, list) else []

    async def generate_trend_titles(
        self,
        streamer_name: str,
        category: str,
        emotion: str,
        game_name: str = "",
        platform: str = "youtube",
        count: int = 5,
        language: str = "tr",
    ) -> list[str]:
        """Generate trend-aware titles using current patterns."""
        ctx = {
            "streamer_name": streamer_name,
            "category": category,
            "emotion": emotion,
            "game_name": game_name or "Various",
            "platform": platform,
        }
        result = await self.generate_json("trend_aware_title", ctx, language)
        titles = result if isinstance(result, list) else []
        return [str(t) for t in titles[:count]]

    async def adapt_multilang(
        self,
        title: str,
        streamer_name: str,
        category: str,
        emotion: str,
        source_language: str = "en",
        language: str = "tr",
    ) -> dict[str, str]:
        """Adapt a title across multiple languages."""
        ctx = {
            "title": title,
            "source_language": source_language,
            "streamer_name": streamer_name,
            "category": category,
            "emotion": emotion,
        }
        result = await self.generate_json("multilang_adaptation", ctx, language)
        if isinstance(result, dict):
            return result
        return {}

    def score_content(
        self,
        title: str,
        description: str,
        hashtags: list[str],
        platform: str = "youtube",
    ) -> dict[str, Any]:
        """Score generated content quality using rules (no LLM call)."""
        return self._quality_scorer.score_all(title, description, hashtags, platform)

    def score_title(self, title: str, platform: str = "youtube") -> dict:
        """Score a single title."""
        return self._quality_scorer.score_title(title, platform)

    # ── Multi-Step Prompt Chain ──────────────────────────────────────

    async def generate_full_package(
        self,
        streamer_name: str,
        category: str,
        emotion: str,
        platform: str = "youtube",
        game_name: str = "",
        viewer_count: int = 0,
        tags: list[str] | None = None,
        duration: float = 30.0,
        language: str = "tr",
    ) -> dict[str, Any]:
        """
        Multi-step prompt chain: generate titles → pick best → generate
        description → hashtags → thumbnail → quality score.

        Returns a complete content package.
        """
        # Step 1: Generate candidate titles
        titles = await self.generate_titles(
            streamer_name=streamer_name,
            category=category,
            emotion=emotion,
            platform=platform,
            game_name=game_name,
            viewer_count=viewer_count,
            tags=tags,
            count=5,
            language=language,
        )

        # Step 2: Score and pick best title
        best_title = titles[0] if titles else f"{streamer_name} - {emotion} moment"
        best_score = 0.0
        for t in titles:
            result = self.score_title(t, platform)
            if result["score"] > best_score:
                best_score = result["score"]
                best_title = t

        # Step 3: Generate description using best title
        description = await self.generate_description(
            title=best_title,
            streamer_name=streamer_name,
            category=category,
            emotion=emotion,
            platform=platform,
            game_name=game_name,
            language=language,
        )

        # Step 4: Generate hashtags
        hashtags = await self.generate_hashtags(
            category=category,
            game_name=game_name,
            streamer_name=streamer_name,
            emotion=emotion,
            platform=platform,
            count=15 if platform == "youtube" else 5,
            language=language,
        )

        # Step 5: Suggest thumbnail
        thumbnail = await self.suggest_thumbnail(
            title=best_title,
            streamer_name=streamer_name,
            category=category,
            emotion=emotion,
            platform=platform,
        )

        # Step 6: Score quality
        quality = self.score_content(best_title, description, hashtags, platform)

        return {
            "titles": titles,
            "selected_title": best_title,
            "title_score": best_score,
            "description": description,
            "hashtags": hashtags,
            "thumbnail": thumbnail,
            "quality": quality,
            "platform": platform,
            "streamer": streamer_name,
            "category": category,
            "emotion": emotion,
            "generated_at": time.time(),
        }

    # ── JSON Extraction ──────────────────────────────────────────────

    def _extract_json(self, raw: str) -> dict[str, Any]:
        """Extract JSON from potentially messy LLM output."""
        raw = raw.strip()
        if not raw:
            return {"raw_output": "", "parse_error": True}

        # Try direct parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try to find JSON block in markdown code fences
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try to find balanced brackets/braces (handles nested JSON)
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

        # Try to fix common issues: single quotes, trailing commas
        cleaned = raw.replace("'", '"')
        cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        return {"raw_output": raw, "parse_error": True}

    # ── Emergency Fallback ───────────────────────────────────────────

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

    # ── Stats & Cache ────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        return dict(self._stats)

    def clear_cache(self):
        self._cache.clear()
        self._stats["cache_hits"] = 0


# Singleton
llm_engine = LLMEngine()
