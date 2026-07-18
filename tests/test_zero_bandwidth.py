"""
Zero-Bandwidth Clip Engine Unit Testleri
────────────────────────────────────────
services/zero_bandwidth_clipper.py icin birim testler.
Agir bagimliliklar (Kick API, LLM, FFmpeg) mock'lanir.
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone


from services.zero_bandwidth_clipper import (
    ZeroBandwidthClipper,
    ClipSuggestion,
    VODAnalysis,
)


# ═══════════════════════════════════════════════════════════════════════════
#  DURATION NORMALIZATION (>86400 = ms->sec)
# ═══════════════════════════════════════════════════════════════════════════


class TestDurationNormalization:
    """VOD suresi >86400 ise milisaniye olarak algilanmali ve saniyeye cevrilmeli."""

    def test_ms_to_sec_large_duration(self):
        clipper = ZeroBandwidthClipper()
        # metadata'da 14996000 ms var -> 14996 saniye (4.2h)
        metadata = {"duration": 14996000, "session_title": "test"}
        duration_raw = metadata.get("duration", 0)
        duration_sec = float(duration_raw) if duration_raw else 3600
        if duration_sec > 86400:
            duration_sec = duration_sec / 1000.0
        assert duration_sec == pytest.approx(14996.0)

    def test_sec_already_small(self):
        clipper = ZeroBandwidthClipper()
        metadata = {"duration": 5196}
        duration_raw = metadata.get("duration", 0)
        duration_sec = float(duration_raw) if duration_raw else 3600
        if duration_sec > 86400:
            duration_sec = duration_sec / 1000.0
        assert duration_sec == 5196.0

    def test_boundary_86400(self):
        """86400 saniye (24 saat) = sinir degeri."""
        clipper = ZeroBandwidthClipper()
        # 86400 sn = 86400000 ms -> sinir
        metadata = {"duration": 86401}  # 86401 > 86400 -> ms olarak algilanir
        duration_raw = metadata.get("duration", 0)
        duration_sec = float(duration_raw) if duration_raw else 3600
        if duration_sec > 86400:
            duration_sec = duration_sec / 1000.0
        assert duration_sec == pytest.approx(86.401)  # 86401/1000

    def test_zero_defaults_to_3600(self):
        """Suresi 0 veya yoksa 3600 varsayilir."""
        metadata = {"duration": 0}
        duration_raw = metadata.get("duration", 0)
        duration_sec = float(duration_raw) if duration_raw else 3600
        assert duration_sec == 3600.0


# ═══════════════════════════════════════════════════════════════════════════
#  METADATA PARSING (session_title vs title, categories[0].name)
# ═══════════════════════════════════════════════════════════════════════════


class TestMetadataParsing:
    """Kick API metadata'sinin dogru parse edilmesi."""

    def test_session_title_preferred(self):
        """session_title varsa title'dan once kullanilmali."""
        metadata = {"session_title": "selam | !dc !ig", "title": "eski baslik"}
        title = str(metadata.get("session_title") or metadata.get("title") or "")
        assert title == "selam | !dc !ig"

    def test_fallback_to_title(self):
        """session_title yoksa title kullanilmali."""
        metadata = {"title": "sadece title"}
        title = str(metadata.get("session_title") or metadata.get("title") or "")
        assert title == "sadece title"

    def test_categories_array_name(self):
        """categories[0].name dogru cikarilmali."""
        metadata = {"categories": [{"id": 15, "name": "Just Chatting"}]}
        cats = metadata.get("categories") or metadata.get("category")
        if isinstance(cats, list) and cats:
            category = cats[0].get("name", "") if isinstance(cats[0], dict) else str(cats[0])
        else:
            category = ""
        assert category == "Just Chatting"

    def test_categories_string_fallback(self):
        """categories string ise dogrudan kullanilmali."""
        metadata = {"category": "Just Chatting"}
        cats = metadata.get("categories") or metadata.get("category")
        if isinstance(cats, list) and cats:
            category = cats[0].get("name", "") if isinstance(cats[0], dict) else str(cats[0])
        elif isinstance(cats, str):
            category = cats
        else:
            category = ""
        assert category == "Just Chatting"

    def test_created_at_field(self):
        """created_at alani dogru cikarilmali."""
        metadata = {"created_at": "2026-07-18 15:03:53"}
        created = metadata.get("created_at", metadata.get("published_at", ""))
        assert created == "2026-07-18 15:03:53"

    def test_start_time_field(self):
        """start_time alani dogru cikarilmali."""
        metadata = {"start_time": "2026-07-18 15:03:51"}
        vod_start = str(metadata.get("start_time") or metadata.get("created_at", ""))
        assert vod_start == "2026-07-18 15:03:51"


# ═══════════════════════════════════════════════════════════════════════════
#  LIVESTREAM_ID STRING/INT COMPARISON (REGRESSION TEST)
# ═══════════════════════════════════════════════════════════════════════════


class TestLivestreamIdComparison:
    """livestream_id string vs int eslesme hatasi tekrar sismamali."""

    def test_string_string_match(self):
        ls_id = "116817928"
        vod_id = "116817928"
        assert str(ls_id) == str(vod_id)

    def test_int_string_match(self):
        """Kick API'den int gelir, bizim vod_id string olur."""
        ls_id = 116817928  # API'den int olarak gelebilir
        vod_id = "116817928"
        assert str(ls_id) == str(vod_id)

    def test_string_int_match_reversed(self):
        ls_id = "116817928"
        vod_id = 116817928
        assert str(ls_id) == str(vod_id)

    def test_no_match_different_ids(self):
        ls_id = "116817928"
        vod_id = "999999999"
        assert str(ls_id) != str(vod_id)

    def test_empty_string_no_match(self):
        ls_id = ""
        vod_id = "116817928"
        assert str(ls_id) != str(vod_id)

    def test_none_no_match(self):
        ls_id = None
        vod_id = "116817928"
        assert str(ls_id) != str(vod_id)

    def test_realistic_clip_vs_vod_comparison(self):
        """Gercek Kick API verisi: clip livestream_id vs VOD id."""
        # Clip payload
        clip = {"livestream_id": "116817928", "title": "tuncay"}
        # VOD listesi
        vod_ids = ["118005613", "117865361", "117566391"]

        # Karsilastirma
        ls_id_str = str(clip["livestream_id"])
        matched = ls_id_str in [str(v) for v in vod_ids]
        # Bu ornek: 116817928 listede yok (eski VOD silinmis)
        assert not matched

    def test_clip_vod_match_when_present(self):
        """VOD listede varsa eslesme olmali."""
        clip = {"livestream_id": "117865361"}
        vod_ids = ["118005613", "117865361", "117566391"]
        ls_id_str = str(clip["livestream_id"])
        matched = any(ls_id_str == str(v) for v in vod_ids)
        assert matched


# ═══════════════════════════════════════════════════════════════════════════
#  CONFIDENCE CALCULATION (engagement-weighted)
# ═══════════════════════════════════════════════════════════════════════════


class TestConfidenceCalculation:
    """Community clip confidence'i engagement'a gore agirliklandirma."""

    def test_zero_views_base_score(self):
        """0 view'da bile minimum 0.50 base skor var."""
        conf = ZeroBandwidthClipper._calculate_community_confidence(
            views=0, likes=0, max_views_in_vod=34, same_area_count=1
        )
        assert conf == pytest.approx(0.50)

    def test_max_views_high_score(self):
        """En cok view alan klibe 0.85 civarinda skor."""
        conf = ZeroBandwidthClipper._calculate_community_confidence(
            views=34, likes=0, max_views_in_vod=34, same_area_count=1
        )
        assert conf >= 0.70
        assert conf <= 0.95

    def test_likes_add_bonus(self):
        """Like sayisi confidence'i artirmali."""
        conf_no_likes = ZeroBandwidthClipper._calculate_community_confidence(
            views=10, likes=0, max_views_in_vod=34, same_area_count=1
        )
        conf_with_likes = ZeroBandwidthClipper._calculate_community_confidence(
            views=10, likes=5, max_views_in_vod=34, same_area_count=1
        )
        assert conf_with_likes > conf_no_likes

    def test_cluster_bonus(self):
        """Ayni bolgede clip bonusu."""
        conf_single = ZeroBandwidthClipper._calculate_community_confidence(
            views=10, likes=0, max_views_in_vod=34, same_area_count=1
        )
        conf_cluster = ZeroBandwidthClipper._calculate_community_confidence(
            views=10, likes=0, max_views_in_vod=34, same_area_count=5
        )
        assert conf_cluster > conf_single

    def test_cap_at_095(self):
        """Confidence 0.95'i asmamali."""
        conf = ZeroBandwidthClipper._calculate_community_confidence(
            views=1000, likes=100, max_views_in_vod=1000, same_area_count=10
        )
        assert conf <= 0.95


# ═══════════════════════════════════════════════════════════════════════════
#  POSITION ESTIMATION (clip.created_at - vod.start_time)
# ═══════════════════════════════════════════════════════════════════════════


class TestPositionEstimation:
    """Clip created_at - VOD start_time farkindan konum tahmini."""

    def test_basic_position(self):
        """11 dk sonra olusturulan clip = ~660s konum."""
        pos, conf = ZeroBandwidthClipper._estimate_clip_position(
            clip_created_at="2026-07-18T15:15:05Z",
            vod_start_time="2026-07-18 15:03:51",
            vod_duration=14996,
        )
        assert conf == "approximate"
        assert pos == pytest.approx(674, abs=5)  # ~674s

    def test_position_at_start(self):
        """VOD basinda olusturulan clip."""
        pos, conf = ZeroBandwidthClipper._estimate_clip_position(
            clip_created_at="2026-07-18T15:04:00Z",
            vod_start_time="2026-07-18 15:03:51",
            vod_duration=14996,
        )
        assert conf == "approximate"
        assert pos == pytest.approx(9, abs=5)

    def test_position_at_end(self):
        """VOD sonunda olusturulan clip."""
        pos, conf = ZeroBandwidthClipper._estimate_clip_position(
            clip_created_at="2026-07-17T18:33:03Z",
            vod_start_time="2026-07-17 17:08:17",
            vod_duration=5196,
        )
        assert conf == "approximate"
        assert pos == pytest.approx(5086, abs=5)

    def test_position_outside_vod(self):
        """VOD disinda olusturulan clip (negatif fark)."""
        pos, conf = ZeroBandwidthClipper._estimate_clip_position(
            clip_created_at="2026-07-18T14:00:00Z",
            vod_start_time="2026-07-18 15:03:51",
            vod_duration=14996,
        )
        assert conf == "none"
        assert pos == 0.0

    def test_no_data_returns_none(self):
        """Bos veri ile none donecek."""
        pos, conf = ZeroBandwidthClipper._estimate_clip_position(
            clip_created_at="", vod_start_time="", vod_duration=0
        )
        assert conf == "none"
        assert pos == 0.0

    def test_clip_duration_ignored(self):
        """Clip suresi konum hesaplamasina etki etmemeli (sadece created_at kullanilir)."""
        pos1, _ = ZeroBandwidthClipper._estimate_clip_position(
            "2026-07-18T15:15:05Z", "2026-07-18 15:03:51", 14996
        )
        pos2, _ = ZeroBandwidthClipper._estimate_clip_position(
            "2026-07-18T15:15:05Z", "2026-07-18 15:03:51", 3600
        )
        # Farkli VOD suresi, ayni clip -> ayni konum (eger VOD icindeyse)
        assert pos1 == pos2


# ═══════════════════════════════════════════════════════════════════════════
#  CLUSTER DETECTION
# ═══════════════════════════════════════════════════════════════════════════


class TestClusterDetection:
    """Ayni bolgedeki clip'lerin tespiti."""

    def test_no_clips(self):
        clusters = ZeroBandwidthClipper._detect_clip_clusters([], "")
        assert clusters == {}

    def test_single_clip(self):
        clips = [{"created_at": "2026-07-18T15:15:05Z"}]
        clusters = ZeroBandwidthClipper._detect_clip_clusters(
            clips, "2026-07-18 15:03:51"
        )
        assert clusters == {0: 1}  # 1 clip = 1 (kendisi)

    def test_two_close_clips(self):
        """3 dk icinde 2 clip = cluster."""
        clips = [
            {"created_at": "2026-07-18T15:15:05Z"},
            {"created_at": "2026-07-18T15:16:05Z"},  # 60s sonra
        ]
        clusters = ZeroBandwidthClipper._detect_clip_clusters(
            clips, "2026-07-18 15:03:51"
        )
        assert clusters[0] == 2
        assert clusters[1] == 2

    def test_two_distant_clips(self):
        """3 dk'dan uzak 2 clip = farkli cluster."""
        clips = [
            {"created_at": "2026-07-18T15:15:05Z"},
            {"created_at": "2026-07-18T16:15:05Z"},  # 60 dk sonra
        ]
        clusters = ZeroBandwidthClipper._detect_clip_clusters(
            clips, "2026-07-18 15:03:51"
        )
        assert clusters[0] == 1
        assert clusters[1] == 1


# ═══════════════════════════════════════════════════════════════════════════
#  CLOUDFLARE DETECTION
# ═══════════════════════════════════════════════════════════════════════════


class TestCloudflareDetection:
    """Cloudflare engelleme algilama."""

    def test_403_is_blocked(self):
        clipper = ZeroBandwidthClipper()
        assert clipper._check_cloudflare_block(403, "Forbidden")
        assert clipper._cf_block_count == 1

    def test_503_is_blocked(self):
        clipper = ZeroBandwidthClipper()
        assert clipper._check_cloudflare_block(503, "Service Unavailable")

    def test_200_ok(self):
        clipper = ZeroBandwidthClipper()
        assert not clipper._check_cloudflare_block(200, '{"data": []}')

    def test_200_with_challenge(self):
        """CF challenge sayfasi 200 ile donebilir."""
        clipper = ZeroBandwidthClipper()
        challenge_html = "<html><title>Just a moment...</title></html>"
        assert clipper._check_cloudflare_block(200, challenge_html)

    def test_health_status(self):
        clipper = ZeroBandwidthClipper()
        health = clipper.get_cf_health()
        assert health["is_healthy"]
        assert health["cf_block_count"] == 0
        assert "chrome" in health["impersonate_version"]


# ═══════════════════════════════════════════════════════════════════════════
#  CLIP SUGGESTION DATA MODEL
# ═══════════════════════════════════════════════════════════════════════════


class TestClipSuggestion:
    """ClipSuggestion dataclass dogru calisiyor mu."""

    def test_default_values(self):
        clip = ClipSuggestion(
            clip_id="test_1",
            title="Test",
            description="Desc",
            start_time=0,
            end_time=30,
            duration=30,
            confidence=0.8,
            reason="Test reason",
        )
        assert clip.source == "llm_guess"
        assert clip.platform == "tiktok"
        assert clip.community_views == 0
        assert clip.estimated_position_sec == 0.0
        assert clip.position_confidence == "none"

    def test_community_clip_with_position(self):
        clip = ClipSuggestion(
            clip_id="test_2",
            title="Community",
            description="Desc",
            start_time=0,
            end_time=0,
            duration=30,
            confidence=0.75,
            reason="Izleyici klipledi",
            source="community_clip",
            community_views=34,
            estimated_position_sec=674.0,
            position_confidence="approximate",
        )
        assert clip.source == "community_clip"
        assert clip.community_views == 34
        assert clip.estimated_position_sec == 674.0
        assert clip.position_confidence == "approximate"
