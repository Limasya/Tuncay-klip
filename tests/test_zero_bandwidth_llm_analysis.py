"""
Zero-Bandwidth -- LLM Analysis Pure Function Unit Tests
─────────────────────────────────────────────────────────
Direct module-level function tests for services/zero_bandwidth/llm_analysis.py
"""
import pytest
from services.zero_bandwidth.llm_analysis import _parse_llm_response
from services.zero_bandwidth.models import VODAnalysis, ClipSuggestion


class TestParseLlmResponse:
    def test_valid_json(self):
        text = '{"summary": "test", "highlights": [{"start_sec": 10, "end_sec": 20, "title": "c", "reason": "r", "confidence": 0.8}]}'
        result = _parse_llm_response(text)
        assert result["summary"] == "test"
        assert len(result["highlights"]) == 1

    def test_json_in_code_block(self):
        text = '```json\n{"summary": "code block", "highlights": []}\n```'
        result = _parse_llm_response(text)
        assert result["summary"] == "code block"

    def test_json_in_code_block_no_lang(self):
        text = '```\n{"summary": "no lang", "highlights": []}\n```'
        result = _parse_llm_response(text)
        assert result["summary"] == "no lang"

    def test_extra_text_around_json(self):
        text = 'Here is the result:\n{"summary": "extra", "highlights": [{"start_sec": 0, "end_sec": 10, "title": "x", "reason": "y", "confidence": 0.5}]}\nDone.'
        result = _parse_llm_response(text)
        assert result["summary"] == "extra"

    def test_unparseable_returns_fallback(self):
        text = "This is not JSON at all"
        result = _parse_llm_response(text)
        assert result["summary"] == "JSON parse edilemedi"
        assert result["highlights"] == []

    def test_empty_string(self):
        result = _parse_llm_response("")
        assert result["summary"] == "JSON parse edilemedi"

    def test_malformed_json_object(self):
        text = '{"summary": "test" "highlights": []}'
        result = _parse_llm_response(text)
        assert result["summary"] == "JSON parse edilemedi"


class TestBuildClipSuggestions:
    """Test build_clip_suggestions via import."""

    def test_module_imports(self):
        from services.zero_bandwidth.llm_analysis import build_clip_suggestions
        assert callable(build_clip_suggestions)
