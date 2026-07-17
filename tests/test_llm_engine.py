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
