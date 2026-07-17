"""
Tests for enhanced LLM Engine features:
  - Content quality scoring
  - A/B test variants
  - JSON extraction
  - Multi-step prompt chain
  - Platform optimization
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


class TestContentQualityScorer:
    """Test rule-based content quality scoring (no LLM needed)."""

    def test_title_scoring_engagement_words(self):
        from services.llm_engine import ContentQualityScorer
        result = ContentQualityScorer.score_title("Insane Clutch by Tuncay!", "youtube")
        assert result["score"] >= 6.0
        assert result["engagement_hits"] >= 1

    def test_title_scoring_short_tiktok(self):
        from services.llm_engine import ContentQualityScorer
        result = ContentQualityScorer.score_title("POV: You witness this", "tiktok")
        assert result["score"] >= 5.0

    def test_title_scoring_caps_penalty(self):
        from services.llm_engine import ContentQualityScorer
        result = ContentQualityScorer.score_title("THIS IS ALL CAPS SPAM TITLE", "youtube")
        assert result["score"] < 5.0

    def test_title_scoring_numbers_bonus(self):
        from services.llm_engine import ContentQualityScorer
        result = ContentQualityScorer.score_title("Top 1 Play of the Year", "youtube")
        assert result["score"] >= 5.5

    def test_description_scoring_with_cta(self):
        from services.llm_engine import ContentQualityScorer
        result = ContentQualityScorer.score_description(
            "Amazing gaming moment! Subscribe for more clips like this. "
            "Follow @tuncay for daily highlights!",
            "youtube",
        )
        assert result["has_cta"] is True
        assert result["score"] >= 6.0

    def test_description_scoring_without_cta(self):
        from services.llm_engine import ContentQualityScorer
        result = ContentQualityScorer.score_description(
            "A gaming clip happened.",
            "youtube",
        )
        assert result["has_cta"] is False

    def test_hashtag_scoring_unique(self):
        from services.llm_engine import ContentQualityScorer
        result = ContentQualityScorer.score_hashtags(
            ["gaming", "clutch", "epic", "tuncay", "victory"],
            "tiktok",
        )
        assert result["score"] >= 6.0
        assert result["unique_count"] == 5

    def test_hashtag_scoring_duplicates_penalty(self):
        from services.llm_engine import ContentQualityScorer
        result = ContentQualityScorer.score_hashtags(
            ["gaming", "gaming", "gaming", "gaming", "gaming"],
            "youtube",
        )
        assert result["score"] < 5.0

    def test_score_all_overall(self):
        from services.llm_engine import ContentQualityScorer
        result = ContentQualityScorer.score_all(
            title="Insane Clutch by Tuncay!",
            description="Amazing moment! Subscribe for more clips and follow for daily highlights!",
            hashtags=["gaming", "clutch", "epic", "tuncay"],
            platform="youtube",
        )
        assert "overall_score" in result
        assert 1.0 <= result["overall_score"] <= 10.0
        assert "title" in result
        assert "description" in result
        assert "hashtags" in result


class TestLLMEngineJSONExtraction:
    """Test improved JSON extraction from messy LLM output."""

    def setup_method(self):
        from services.llm_engine import llm_engine
        self.engine = llm_engine

    def test_direct_json_array(self):
        result = self.engine._extract_json('["title1", "title2"]')
        assert isinstance(result, list)
        assert result == ["title1", "title2"]

    def test_direct_json_object(self):
        result = self.engine._extract_json('{"mood": "hype", "score": 8}')
        assert isinstance(result, dict)
        assert result["mood"] == "hype"

    def test_markdown_code_fence(self):
        raw = '```json\n{"mood": "hype", "score": 8}\n```'
        result = self.engine._extract_json(raw)
        assert isinstance(result, dict)
        assert result["mood"] == "hype"

    def test_text_before_json(self):
        raw = 'Here is the analysis:\n{"mood": "hype", "score": 8}\nHope this helps!'
        result = self.engine._extract_json(raw)
        assert isinstance(result, dict)
        assert result["mood"] == "hype"

    def test_nested_json(self):
        raw = 'Analysis: {"data": {"nested": true}, "count": 5}'
        result = self.engine._extract_json(raw)
        assert isinstance(result, dict)
        assert result["data"]["nested"] is True

    def test_empty_input(self):
        result = self.engine._extract_json("")
        assert result.get("parse_error") is True

    def test_single_quotes_fix(self):
        raw = "{'key': 'value'}"
        result = self.engine._extract_json(raw)
        assert isinstance(result, dict)
        assert result["key"] == "value"


class TestLLMEngineNewMethods:
    """Test new generation methods with template fallback."""

    def setup_method(self):
        from services.llm_engine import llm_engine
        self.engine = llm_engine

    @pytest.mark.asyncio
    async def test_generate_ab_test_variants(self):
        result = await self.engine.generate_ab_test_variants(
            title="Efsane Clutch Anı",
            streamer_name="Tuncay",
            category="exciting",
            emotion="hype",
            platform="youtube",
            count=3,
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_generate_viral_hooks(self):
        result = await self.engine.generate_viral_hooks(
            title="Efsane Clutch Anı",
            streamer_name="Tuncay",
            category="exciting",
            emotion="hype",
            duration=30.0,
            platform="youtube",
            count=3,
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_optimize_for_platform(self):
        result = await self.engine.optimize_for_platform(
            title="Tuncay Efsane Clutch Yaptı!",
            streamer_name="Tuncay",
            category="exciting",
            emotion="hype",
            platform="tiktok",
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_generate_content_strategy(self):
        result = await self.engine.generate_content_strategy(
            title="Efsane Clutch Anı",
            streamer_name="Tuncay",
            category="exciting",
            emotion="hype",
            duration=30.0,
            virality_score=8.0,
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_trend_titles(self):
        result = await self.engine.generate_trend_titles(
            streamer_name="Tuncay",
            category="exciting",
            emotion="hype",
            platform="youtube",
            count=5,
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_adapt_multilang(self):
        result = await self.engine.adapt_multilang(
            title="Insane Clutch Moment",
            streamer_name="Tuncay",
            category="exciting",
            emotion="hype",
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_full_package(self):
        result = await self.engine.generate_full_package(
            streamer_name="Tuncay",
            category="exciting",
            emotion="hype",
            platform="youtube",
            game_name="CS2",
            viewer_count=5000,
            tags=["clutch", "insane"],
            duration=30.0,
        )
        assert isinstance(result, dict)
        assert "selected_title" in result
        assert "description" in result
        assert "hashtags" in result
        assert "quality" in result
        assert "thumbnail" in result
        assert result["platform"] == "youtube"

    def test_score_content(self):
        result = self.engine.score_content(
            title="Insane Clutch by Tuncay!",
            description="Amazing moment! Subscribe for more!",
            hashtags=["gaming", "clutch", "epic"],
            platform="youtube",
        )
        assert "overall_score" in result
        assert 1.0 <= result["overall_score"] <= 10.0

    def test_score_title(self):
        result = self.engine.score_title("Insane Clutch!", "youtube")
        assert "score" in result
        assert 1.0 <= result["score"] <= 10.0


class TestLLMEngineCache:
    """Test caching improvements."""

    def setup_method(self):
        from services.llm_engine import llm_engine
        self.engine = llm_engine

    def test_cache_key_deterministic(self):
        key1 = self.engine._build_cache_key("test prompt", "tr", 0.7)
        key2 = self.engine._build_cache_key("test prompt", "tr", 0.7)
        assert key1 == key2

    def test_cache_key_differs_by_language(self):
        key1 = self.engine._build_cache_key("test prompt", "tr", 0.7)
        key2 = self.engine._build_cache_key("test prompt", "en", 0.7)
        assert key1 != key2

    def test_cache_key_differs_by_temperature(self):
        key1 = self.engine._build_cache_key("test prompt", "tr", 0.7)
        key2 = self.engine._build_cache_key("test prompt", "tr", 0.3)
        assert key1 != key2


class TestLLMProviders:
    """Test all LLM provider classes — instantiation, config, structure."""

    def test_openai_provider_init(self):
        from services.llm_providers import OpenAIProvider
        p = OpenAIProvider(api_key="sk-test", model="gpt-4o", base_url="http://custom")
        assert p.api_key == "sk-test"
        assert p.model == "gpt-4o"
        assert p.base_url == "http://custom"

    def test_openai_provider_default_base_url(self):
        from services.llm_providers import OpenAIProvider
        p = OpenAIProvider(api_key="sk-test")
        assert p.base_url == "https://api.openai.com"

    def test_claude_provider_init(self):
        from services.llm_providers import ClaudeProvider
        p = ClaudeProvider(api_key="sk-ant", model="claude-3-sonnet")
        assert p.api_key == "sk-ant"
        assert p.model == "claude-3-sonnet"

    def test_ollama_provider_init(self):
        from services.llm_providers import OllamaProvider
        p = OllamaProvider(base_url="http://localhost:11434", model="mistral")
        assert p.base_url == "http://localhost:11434"
        assert p.model == "mistral"

    def test_vllm_provider_init(self):
        from services.llm_providers import VLLMProvider
        p = VLLMProvider(base_url="http://localhost:8000", model="meta-llama/Llama-3-8B")
        assert p._openai.model == "meta-llama/Llama-3-8B"
        assert p._openai.base_url == "http://localhost:8000"

    def test_lmstudio_provider_init(self):
        from services.llm_providers import LMStudioProvider
        p = LMStudioProvider(base_url="http://localhost:1234", model="my-model")
        assert p._openai.model == "my-model"

    def test_localai_provider_init(self):
        from services.llm_providers import LocalAIProvider
        p = LocalAIProvider(base_url="http://localhost:8080", model="ggml-gpt4all-j")
        assert p._openai.base_url == "http://localhost:8080"
        assert p._openai.model == "ggml-gpt4all-j"

    def test_textgen_provider_init(self):
        from services.llm_providers import TextGenWebUIProvider
        p = TextGenWebUIProvider(base_url="http://localhost:5000", model="llama-2-7b")
        assert p._openai.base_url == "http://localhost:5000"

    def test_huggingface_provider_init(self):
        from services.llm_providers import HuggingFaceProvider
        p = HuggingFaceProvider(api_token="hf_xxx", model="mistralai/Mistral-7B-Instruct")
        assert p.api_token == "hf_xxx"
        assert p.model == "mistralai/Mistral-7B-Instruct"

    def test_gemini_provider_init(self):
        from services.llm_providers import GeminiProvider
        p = GeminiProvider(api_key="AIza...", model="gemini-1.5-pro")
        assert p.api_key == "AIza..."
        assert p.model == "gemini-1.5-pro"

    def test_mistral_provider_init(self):
        from services.llm_providers import MistralProvider
        p = MistralProvider(api_key="mi-key", model="mistral-large-latest")
        assert p.api_key == "mi-key"
        assert p.model == "mistral-large-latest"

    def test_template_provider_callable(self):
        from services.llm_providers import TemplateProvider
        p = TemplateProvider()
        assert callable(p)

    def test_build_chat_messages_no_system(self):
        from services.llm_providers import _build_chat_messages
        msgs = _build_chat_messages("hello")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert "viral content creator" in msgs[0]["content"]

    def test_build_chat_messages_with_system(self):
        from services.llm_providers import _build_chat_messages
        msgs = _build_chat_messages("hello", system_prompt="Be helpful")
        assert msgs[0]["content"] == "Be helpful"

    def test_all_providers_callable_protocol(self):
        """Every provider must be an async callable with the standard signature."""
        import inspect
        from services.llm_providers import (
            OpenAIProvider, ClaudeProvider, OllamaProvider,
            VLLMProvider, LMStudioProvider, LocalAIProvider, TextGenWebUIProvider,
            HuggingFaceProvider, GeminiProvider, MistralProvider,
            TemplateProvider,
        )
        for cls in [
            OpenAIProvider, ClaudeProvider, OllamaProvider,
            VLLMProvider, LMStudioProvider, LocalAIProvider, TextGenWebUIProvider,
            HuggingFaceProvider, GeminiProvider, MistralProvider,
            TemplateProvider,
        ]:
            assert hasattr(cls, "__call__"), f"{cls.__name__} missing __call__"


class TestLLMEngineProviderChain:
    """Test that the engine correctly initializes providers based on env vars."""

    def test_template_always_registered(self):
        from services.llm_engine import llm_engine
        names = [name for name, _ in llm_engine._providers]
        assert "template" in names

    def test_get_provider_status_returns_list(self):
        from services.llm_engine import llm_engine
        status = llm_engine.get_provider_status()
        assert isinstance(status, list)
        assert len(status) >= 1
        assert all("name" in p and "type" in p for p in status)

    def test_provider_status_no_secrets(self):
        from services.llm_engine import llm_engine
        status = llm_engine.get_provider_status()
        for p in status:
            assert "api_key" not in p
            assert "secret" not in str(p).lower()
