"""
AI generator ve utils testleri.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ai_generator import ai_title_generator, TITLE_TEMPLATES, BASE_HASHTAGS
from src.utils import (
    format_duration, format_file_size, clean_filename,
    timestamp_to_filename, ensure_dir,
)


class TestAITitleGenerator:
    """AI baslik/hashtag olusturucu testleri."""

    def test_generate_title_returns_string(self):
        title = ai_title_generator.generate_title(
            emotion="happy",
            streamer_name="TestYayinci",
            category="funny",
        )
        assert isinstance(title, str)
        assert len(title) > 0

    def test_generate_title_with_viewers(self):
        title = ai_title_generator.generate_title(
            emotion="excited",
            streamer_name="Tuncay",
            viewer_count=5000,
            category="exciting",
        )
        assert isinstance(title, str)
        assert "Tuncay" in title or "excited" in title.lower() or "Excited" in title

    def test_generate_description(self):
        desc = ai_title_generator.generate_description(
            title="Test Baslik",
            streamer_name="Tuncay",
            category="funny",
            emotion="happy",
        )
        assert "Test Baslik" in desc
        assert "Tuncay" in desc

    def test_generate_hashtags_youtube(self):
        tags = ai_title_generator.generate_hashtags(
            category="exciting",
            platform="youtube",
        )
        assert isinstance(tags, list)
        assert len(tags) > 0
        assert len(tags) <= 30  # YouTube max

    def test_generate_hashtags_tiktok(self):
        tags = ai_title_generator.generate_hashtags(
            category="funny",
            platform="tiktok",
        )
        assert len(tags) <= 5  # TikTok max

    def test_generate_hashtags_with_game(self):
        tags = ai_title_generator.generate_hashtags(
            category="skill",
            platform="youtube",
            game_name="Valorant",
            streamer_name="Tuncay",
        )
        assert "valorant" in tags or "valorantclips" in tags
        assert "tuncay" in tags

    def test_generate_hashtags_no_duplicates(self):
        tags = ai_title_generator.generate_hashtags(
            category="gaming",
            platform="youtube",
        )
        assert len(tags) == len(set(tags))

    def test_generate_full_metadata(self):
        meta = ai_title_generator.generate_full_metadata(
            emotion="happy",
            category="funny",
            streamer_name="Tuncay",
            viewer_count=1000,
            game_name="CS2",
            platform="youtube",
        )
        assert "title" in meta
        assert "description" in meta
        assert "hashtags" in meta
        assert isinstance(meta["title"], str)
        assert isinstance(meta["description"], str)
        assert isinstance(meta["hashtags"], list)

    def test_all_categories_have_templates(self):
        for cat in ["funny", "exciting", "rage", "victory", "skill"]:
            assert cat in TITLE_TEMPLATES
            assert len(TITLE_TEMPLATES[cat]) > 0

    def test_all_categories_have_base_hashtags(self):
        for cat in ["gaming", "funny", "exciting", "rage", "victory", "skill"]:
            assert cat in BASE_HASHTAGS
            assert len(BASE_HASHTAGS[cat]) > 0


class TestUtils:
    """Yardimci fonksiyon testleri."""

    def test_format_duration_seconds(self):
        assert format_duration(45) == "00:45"

    def test_format_duration_minutes(self):
        assert format_duration(125) == "02:05"

    def test_format_duration_hours(self):
        assert format_duration(3661) == "01:01:01"

    def test_format_file_size_bytes(self):
        assert format_file_size(500) == "500 B"

    def test_format_file_size_kb(self):
        assert "KB" in format_file_size(2048)

    def test_format_file_size_mb(self):
        assert "MB" in format_file_size(5 * 1024 * 1024)

    def test_format_file_size_gb(self):
        assert "GB" in format_file_size(2 * 1024 * 1024 * 1024)

    def test_clean_filename(self):
        assert clean_filename('test<>:"/\\|?*file') == "test_________file"

    def test_clean_filename_normal(self):
        assert clean_filename("normal_file.mp4") == "normal_file.mp4"

    def test_timestamp_to_filename(self):
        result = timestamp_to_filename()
        assert len(result) == 15  # YYYYMMDD_HHMMSS

    def test_ensure_dir(self):
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = os.path.join(tmpdir, "test_subdir")
            result = ensure_dir(new_dir)
            assert result.exists()
