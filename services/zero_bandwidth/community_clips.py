"""
Zero-Bandwidth Clip Engine — Community Clips
─────────────────────────────────────────────
Community clip'leri cekme, normalize etme, filtreleme, cluster tespiti,
guven skoru hesaplama, pozisyon tahmini.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ._config import CHANNEL

logger = logging.getLogger("zero_bandwidth_clipper")

# Cluster tespiti icin pencere boyutu (saniye)
_CLUSTER_WINDOW_SEC = 180


def _parse_ts(ts: str) -> Optional[datetime]:
    """Parse a timestamp string to timezone-aware UTC datetime.

    Handles ISO formats with Z suffix, +00:00 offset, and space-separated
    formats without timezone (assumed UTC).
    """
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


async def fetch_community_clips(
    kick_client,
    vod_id: str,
    cloudflare_checker=None,
) -> list[dict[str, Any]]:
    """Kick API'den community clip'leri cek.

    Once kick_client.list_channel_clips() dener, Cloudflare bypass yapamazsa
    direkt curl_cffi ile CHANNEL sabitini kullanir.

    cloudflare_checker: (status_code, response_text) -> bool fonksiyonu.
    """
    # Strateji 1: kick_client uzerinden (Cloudflare bypass destekliyorsa)
    try:
        raw_clips = await kick_client.list_channel_clips(limit=50, sort="newest")
        if raw_clips:
            clips = []
            for c in raw_clips:
                clip = _normalize_clip(c)
                if clip:
                    clips.append(clip)
            if clips:
                logger.info("kick_client ile %d community clip cekildi", len(clips))
                return clips
    except Exception as e:
        logger.debug("kick_client.list_channel_clips basarisiz: %s", e)

    # Strateji 2: curl_cffi ile direkt API cagrisi
    try:
        from curl_cffi.requests import Session as CurlSession

        clips: list[dict[str, Any]] = []
        session = CurlSession(impersonate="chrome124")

        try:
            resp = session.get(
                f"https://kick.com/api/v2/channels/{CHANNEL}/clips",
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0",
                },
            )

            if cloudflare_checker and cloudflare_checker(resp.status_code, resp.text):
                return []

            if resp.status_code == 200:
                data = resp.json()
                raw_clips = data.get("clips", data) if isinstance(data, dict) else data
                if isinstance(raw_clips, list):
                    for c in raw_clips:
                        clip = _normalize_clip(c)
                        if clip:
                            clips.append(clip)
        finally:
            session.close()

        return clips

    except ImportError:
        logger.warning("curl_cffi yuklu degil, community clips cekilemedi")
        return []
    except Exception as e:
        logger.error("Community clips cekme hatasi: %s", e)
        return []


def _normalize_clip(raw: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Ham clip verisini normalize et."""
    clip_id = str(raw.get("clip_id") or raw.get("id") or "")
    if not clip_id:
        return None

    return {
        "clip_id": clip_id,
        "title": str(raw.get("title", "")),
        "creator": str(raw.get("creator", {}).get("username", "") if isinstance(raw.get("creator"), dict) else raw.get("creator", "")),
        "views": int(raw.get("views", 0) or 0),
        "likes": int(raw.get("likes", 0) or 0),
        "duration": float(raw.get("duration", 0) or 0),
        "clip_url": str(raw.get("clip_url") or raw.get("url") or ""),
        "thumbnail_url": str(raw.get("thumbnail_url") or ""),
        "created_at": str(raw.get("created_at") or ""),
        "livestream_id": str(raw.get("livestream_id") or ""),
    }


def format_clips_for_llm(
    community_clips: list[dict[str, Any]],
    vod_start_time: str = "",
    vod_duration: float = 0,
) -> str:
    """Community clip'leri LLM prompt'u icin formate et."""
    if not community_clips:
        return ""

    lines = ["Mevcut topluluk clip'leri:"]
    for i, clip in enumerate(community_clips[:10], 1):
        pos = ""
        if vod_start_time and vod_duration > 0:
            est = estimate_clip_position(clip, vod_start_time)
            if est is not None:
                pct = (est / vod_duration * 100) if vod_duration > 0 else 0
                pos = f" [~{est:.0f}s, VOD'un %{pct:.1f}]"

        lines.append(
            f"  {i}. \"{clip.get('title', 'Baslik yok')}\" "
            f"(izlenme: {clip.get('views', 0)}, "
            f"begeni: {clip.get('likes', 0)}, "
            f"sure: {clip.get('duration', 0):.0f}s){pos}"
        )

    return "\n".join(lines)


def calculate_community_confidence(
    views: int,
    likes: int,
    max_views: int,
    cluster_size: int,
) -> float:
    """Community clip icin guven skoru hesapla (0.0-0.95).

    Agirlikli hesaplama:
    - Base: 0.50
    - View bonus: max 0.25 (max_views'e oraniyla)
    - Like bonus: max 0.10 (like/oran ile)
    - Cluster bonus: max 0.15 (ayni anda birden fazla clip)
    """
    base = 0.50

    view_bonus = 0.0
    if max_views > 0:
        view_ratio = min(views / max_views, 1.0)
        view_bonus = view_ratio * 0.25

    like_bonus = 0.0
    if views > 0:
        like_ratio = min(likes / views, 1.0)
        like_bonus = like_ratio * 0.10

    cluster_bonus = 0.0
    if cluster_size > 1:
        cluster_bonus = min((cluster_size - 1) * 0.05, 0.15)

    total = base + view_bonus + like_bonus + cluster_bonus
    return min(total, 0.95)


def estimate_clip_position(
    clip: dict[str, Any],
    vod_start_time: str,
) -> Optional[float]:
    """Community clip'in VOD icindeki yaklasik pozisyonunu saniye cinsinden hesapla.

    Tahmini pozisyon = clip.created_at - vod.start_time
    Returns None if timestamps are invalid.
    """
    created_at = clip.get("created_at", "")
    if not created_at or not vod_start_time:
        return None

    clip_dt = _parse_ts(created_at)
    vod_dt = _parse_ts(vod_start_time)
    if not clip_dt or not vod_dt:
        return None

    diff = (clip_dt - vod_dt).total_seconds()
    return diff


def detect_clip_clusters(
    community_clips: list[dict[str, Any]],
    vod_start_time: str,
) -> list[int]:
    """Community clip'leri zamansal yakinliklarina gore cluster'lara ayir.

    Her clip icin o cluster'daki clip sayisini dondur.
    3 dakikalik pencere icindeki clip'ler ayni cluster'a ait.
    """
    if not community_clips:
        return []

    positions = []
    for clip in community_clips:
        pos = estimate_clip_position(clip, vod_start_time)
        positions.append(pos if pos is not None else 0.0)

    sorted_indices = sorted(range(len(positions)), key=lambda i: positions[i])
    cluster_sizes = [0] * len(positions)

    i = 0
    while i < len(sorted_indices):
        cluster_start = positions[sorted_indices[i]]
        j = i
        while j < len(sorted_indices) and (positions[sorted_indices[j]] - cluster_start) <= _CLUSTER_WINDOW_SEC:
            j += 1
        size = j - i
        for k in range(i, j):
            cluster_sizes[sorted_indices[k]] = size
        i = j

    return cluster_sizes


def validate_clip_timing(
    clip: dict[str, Any],
    vod_start: str,
    vod_duration: float,
    tolerance_sec: float = 60.0,
) -> tuple[bool, str]:
    """Community clip'in zamanlamasini dogrula.

    clip.created_at, [vod_start - tolerance, vod_start + duration + tolerance]
    araliginda olmali. Degilse, muhtemelen yanlis livestream_id eslesmesi.

    Returns:
        (is_valid, reason)
    """
    created_at = clip.get("created_at", "")
    if not created_at:
        return True, "created_at yok, pas gecildi"

    if not vod_start:
        return True, "vod_start yok, pas gecildi"

    try:
        clip_dt = _parse_ts(created_at)
        vod_dt = _parse_ts(vod_start)
        if not clip_dt or not vod_dt:
            return True, "tarih parse hatasi, pas gecildi"
    except (ValueError, TypeError):
        return True, "tarih parse hatasi, pas gecildi"

    clip_ts = clip_dt.timestamp()
    vod_start_ts = vod_dt.timestamp()
    vod_end_ts = vod_start_ts + vod_duration

    margin_start = vod_start_ts - tolerance_sec
    margin_end = vod_end_ts + tolerance_sec

    if clip_ts < margin_start:
        hours_before = (vod_start_ts - clip_ts) / 3600
        return False, f"clip VOD'dan {hours_before:.1f} saat once olusturulmus"

    if clip_ts > margin_end:
        hours_after = (clip_ts - vod_end_ts) / 3600
        return False, f"clip VOD bitisinden {hours_after:.1f} saat sonra olusturulmus"

    return True, "zamanlama dogru"


def filter_clips_by_timing(
    community_clips: list[dict[str, Any]],
    vod_start: str,
    vod_duration: float,
    tolerance_sec: float = 60.0,
) -> list[dict[str, Any]]:
    """Community clip'leri zamanlamalarina gore filtrele."""
    valid_clips = []
    for clip in community_clips:
        is_valid, reason = validate_clip_timing(clip, vod_start, vod_duration, tolerance_sec)
        if is_valid:
            valid_clips.append(clip)
        else:
            logger.debug(
                "Clip reddedildi (%s): %s — %s",
                clip.get("clip_id", "?"), clip.get("title", "?"), reason,
            )
    return valid_clips
