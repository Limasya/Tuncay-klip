"""
Zero-Bandwidth Clip Engine — Ana Orkestrator
────────────────────────────────────────────
ZeroBandwidthClipper sinifi: diger modulleri birlestiren orkestrator.
Backward-compatible: eski method imzalari korunur.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from .models import ClipSuggestion, VODAnalysis
from . import vod_metadata as _vod_meta
from . import community_clips as _comm_clips
from . import llm_analysis as _llm
from . import audio_fallback as _audio
from . import alerting as _alert
from . import renderer as _renderer

logger = logging.getLogger("zero_bandwidth_clipper")


class ZeroBandwidthClipper:
    """Sifir bant genisligiyle VOD analizi yapan clip motoru."""

    def __init__(self):
        self._analysis_cache: dict[str, VODAnalysis] = {}
        self._render_dir = Path("data/rendered_clips")
        self._render_dir.mkdir(parents=True, exist_ok=True)
        self.audio_only_fallback_enabled: bool = False

        # Cloudflare tracking
        self._cf_block_count: int = 0
        self._cf_last_block_time: float = 0
        self._cf_alert_logged: bool = False
        self._cf_last_discord_alert_time: float = 0

    @property
    def _CF_IMPERSONATE(self) -> str:
        return _alert.CF_IMPERSONATE

    # ── Cloudflare ────────────────────────────────────────────────

    def _check_cloudflare_block(self, status_code: int, response_text: str) -> bool:
        blocked, new_count, new_logged, new_time = _alert.check_cloudflare_block(
            status_code, response_text,
            self._cf_block_count, self._cf_alert_logged, self._cf_last_discord_alert_time,
        )
        self._cf_block_count = new_count
        self._cf_alert_logged = new_logged
        self._cf_last_discord_alert_time = new_time
        if blocked:
            self._cf_last_block_time = time.monotonic()
        return blocked

    def _send_cf_alert(self, title: str, message: str) -> None:
        self._cf_last_discord_alert_time = _alert._send_cf_alert(
            title, message, self._cf_block_count, self._cf_last_discord_alert_time,
        )

    def get_cf_health(self) -> dict[str, Any]:
        return _alert.get_cf_health(self._cf_block_count, self._cf_last_block_time)

    # ── VOD Metadata ──────────────────────────────────────────────

    @staticmethod
    def _extract_vod_id(url: str) -> Optional[str]:
        return _vod_meta.extract_vod_id(url)

    async def _fetch_vod_metadata_simple(self, vod_url: str) -> Optional[dict[str, Any]]:
        from services.kick_api import kick_service
        return await _vod_meta.fetch_vod_metadata_simple(kick_service, vod_url)

    async def _get_hls_source(self, vod_url: str) -> Optional[str]:
        return await _vod_meta.get_hls_source(vod_url)

    # ── Community Clips (backward-compatible imzalar) ──────────────

    async def _fetch_community_clips(self, vod_id: str) -> list[dict[str, Any]]:
        from services.kick_api import kick_service
        return await _comm_clips.fetch_community_clips(
            kick_service, vod_id, cloudflare_checker=self._check_cloudflare_block,
        )

    @staticmethod
    def _format_clips_for_llm(
        community_clips_list: list[dict[str, Any]],
        vod_start_time: str = "",
        vod_duration: float = 0,
    ) -> str:
        return _comm_clips.format_clips_for_llm(community_clips_list, vod_start_time, vod_duration)

    @staticmethod
    def _calculate_community_confidence(
        views: int = 0,
        likes: int = 0,
        max_views_in_vod: int = 0,
        same_area_count: int = 1,
    ) -> float:
        """Eski imza: max_views_in_vod, same_area_count."""
        return _comm_clips.calculate_community_confidence(
            views, likes, max_views_in_vod, same_area_count,
        )

    @staticmethod
    def _estimate_clip_position(
        clip_created_at: str = "",
        vod_start_time: str = "",
        vod_duration: float = 0,
    ) -> tuple[float, str]:
        """Eski imza: (pos, confidence_str) dondurur."""
        clip = {"created_at": clip_created_at}
        pos = _comm_clips.estimate_clip_position(clip, vod_start_time)
        if pos is None:
            return 0.0, "none"
        if pos < 0:
            return 0.0, "none"
        if vod_duration > 0 and pos > vod_duration:
            return 0.0, "none"
        return pos, "approximate"

    @staticmethod
    def _detect_clip_clusters(
        community_clips_list: list[dict[str, Any]],
        vod_start_time: str,
    ) -> dict[int, int]:
        """Eski imza: {index: cluster_size} dondurur."""
        sizes = _comm_clips.detect_clip_clusters(community_clips_list, vod_start_time)
        return {i: s for i, s in enumerate(sizes)}

    @staticmethod
    def _validate_clip_timing(
        clip: dict[str, Any],
        vod_start: str,
        vod_duration: float,
        tolerance_sec: float = 60.0,
    ) -> tuple[bool, str]:
        """Eski imza: turkce reason string'leri."""
        is_valid, reason = _comm_clips.validate_clip_timing(clip, vod_start, vod_duration, tolerance_sec)
        # Eski reason mapping
        if reason == "created_at yok, pas gecildi":
            reason = "dogrulama_yapilamadi"
        elif reason == "vod_start yok, pas gecildi":
            reason = "dogrulama_yapilamadi"
        elif reason == "tarih parse hatasi, pas gecildi":
            reason = "dogrulama_yapilamadi"
        elif reason == "zamanlama dogru":
            reason = "zaman_araliginda"
        return is_valid, reason

    def _filter_clips_by_timing(self, community_clips_list, vod_start, vod_duration, tolerance_sec=60.0):
        return _comm_clips.filter_clips_by_timing(community_clips_list, vod_start, vod_duration, tolerance_sec)

    # ── LLM Analiz ────────────────────────────────────────────────

    async def _analyze_with_llm(self, metadata, community_clips_list, transcription_text=None):
        return await _llm.analyze_with_llm(
            metadata, community_clips_list, transcription_text,
            format_clips_fn=self._format_clips_for_llm,
        )

    def _build_clip_suggestions(self, vod_id, vod_url, metadata, llm_result, community_clips_list):
        return _llm.build_clip_suggestions(vod_id, vod_url, metadata, llm_result, community_clips_list)

    # ── Audio Fallback ────────────────────────────────────────────

    async def _transcribe_audio_only(self, hls_url: str, duration_sec: float) -> Optional[str]:
        return await _audio.transcribe_audio_only(hls_url, duration_sec)

    # ── Render ────────────────────────────────────────────────────

    async def _validate_mp4(self, path: str, timeout: float = 15) -> bool:
        return await _renderer._validate_mp4(path, timeout)

    async def render_clip(self, vod_url: str, clip: ClipSuggestion) -> dict[str, Any]:
        """Onaylanan bir clip'i indir ve render et."""
        return await _renderer.render_clip(
            vod_url=vod_url,
            clip_start_time=clip.start_time,
            clip_duration=clip.duration,
            clip_id=clip.clip_id,
            output_dir=self._render_dir,
            get_hls_source_fn=self._get_hls_source,
            validate_mp4_fn=self._validate_mp4,
            cloudflare_checker=self._check_cloudflare_block,
        )

    # ── Ana Orkestrasyon ──────────────────────────────────────────

    async def analyze_vod(self, vod_url: str) -> VODAnalysis:
        t0 = time.monotonic()

        vod_id = self._extract_vod_id(vod_url)
        if not vod_id:
            raise ValueError(f"Gecersiz VOD URL: {vod_url}")

        if vod_id in self._analysis_cache:
            return self._analysis_cache[vod_id]

        logger.info("Adim 1a: VOD metadata cekiliyor...")
        metadata = await self._fetch_vod_metadata_simple(vod_url)
        if not metadata:
            raise ValueError(f"VOD metadata cekilemedi: {vod_url}")

        duration_raw = metadata.get("duration", 0)
        duration_sec = float(duration_raw) if duration_raw else 3600
        if duration_sec > 86400:
            duration_sec = duration_sec / 1000.0
        vod_start = str(metadata.get("start_time") or metadata.get("created_at", ""))

        numeric_vod_id = str(metadata.get("id", vod_id))
        community_clips_list = await self._fetch_community_clips(numeric_vod_id)

        if community_clips_list and vod_start and duration_sec > 0:
            before_count = len(community_clips_list)
            community_clips_list = self._filter_clips_by_timing(
                community_clips_list, vod_start, duration_sec,
            )
            after_count = len(community_clips_list)
            if before_count != after_count:
                logger.warning(
                    "Zaman dogrulamasi: %d -> %d clip", before_count, after_count,
                )

        transcription_text = None
        if not community_clips_list and self.audio_only_fallback_enabled:
            hls_url = await self._get_hls_source(vod_url)
            if hls_url:
                transcription_text = await self._transcribe_audio_only(hls_url, duration_sec)

        llm_result = await self._analyze_with_llm(metadata, community_clips_list, transcription_text)
        analysis = self._build_clip_suggestions(vod_id, vod_url, metadata, llm_result, community_clips_list)
        analysis.analysis_time_sec = round(time.monotonic() - t0, 2)

        self._analysis_cache[vod_id] = analysis

        community_count = sum(1 for c in analysis.clips if c.source == "community_clip")
        llm_count = sum(1 for c in analysis.clips if c.source == "llm_guess")
        logger.info(
            "VOD analiz tamamlandi: %s | %d clip (%d community + %d llm) | %.1f KB | %.1f saniye",
            analysis.title[:40], len(analysis.clips), community_count, llm_count,
            analysis.bandwidth_used_kb, analysis.analysis_time_sec,
        )
        return analysis

    async def analyze_all_vods(self, limit: int = 5) -> list[VODAnalysis]:
        from services.kick_api import kick_service
        vods = await kick_service.list_public_vods(limit)
        results = []
        for vod in vods:
            url = str(vod.get("url", ""))
            if url:
                try:
                    results.append(await self.analyze_vod(url))
                except Exception as e:
                    logger.error("VOD analiz hatasi %s: %s", url, e)
        return results

    def get_cached_analysis(self, vod_id: str) -> Optional[VODAnalysis]:
        return self._analysis_cache.get(vod_id)
