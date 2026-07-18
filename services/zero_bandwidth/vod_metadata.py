"""
Zero-Bandwidth Clip Engine — VOD Metadata
─────────────────────────────────────────
VOD metadata cekme, HLS source bulma, VOD ID cikarma.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger("zero_bandwidth_clipper")


def extract_vod_id(url: str) -> Optional[str]:
    """Kick VOD URL'sinden VOD ID'sini cikar."""
    try:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "thetuncay" and parts[1] == "videos":
            return parts[2]
    except Exception:
        pass
    return None


async def fetch_vod_metadata(kick_client, vod_url: str) -> Optional[dict[str, Any]]:
    """Kick API'den VOD metadata cek (kanal video listesi uzerinden).

    Basariyla donecek alanlar: session_title, duration, categories, start_time, created_at
    """
    try:
        from curl_cffi.requests import Session as CurlSession

        vod_id = extract_vod_id(vod_url)
        if not vod_id:
            return None

        cf_block = False
        session = CurlSession(impersonate="chrome124")

        try:
            resp = session.get(
                f"https://kick.com/api/v2/channels/thetuncay/videos",
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                videos = data.get("videos", data) if isinstance(data, dict) else data
                if isinstance(videos, list):
                    for v in videos:
                        if str(v.get("id")) == vod_id:
                            return _normalize_vod_metadata(v, vod_url)
            elif resp.status_code in (403, 503):
                cf_block = True
        finally:
            session.close()

        if cf_block:
            logger.warning("Cloudflare tarafindan engellendi (metadata)")

        return None

    except ImportError:
        logger.warning("curl_cffi yuklu degil, metadata cekilemedi")
        return None
    except Exception as e:
        logger.error("VOD metadata cekme hatasi: %s", e)
        return None


async def fetch_vod_metadata_simple(kick_client, vod_url: str) -> Optional[dict[str, Any]]:
    """Basit metadata cekme: /api/v2/video/{id} endpoint'i."""
    try:
        from curl_cffi.requests import Session as CurlSession

        vod_id = extract_vod_id(vod_url)
        if not vod_id:
            return None

        session = CurlSession(impersonate="chrome124")
        try:
            resp = session.get(
                f"https://kick.com/api/v2/video/{vod_id}",
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("id"):
                    return _normalize_vod_metadata(data, vod_url)
        finally:
            session.close()

        # Fallback: kanal video listesinden cek
        return await fetch_vod_metadata(kick_client, vod_url)

    except ImportError:
        return await fetch_vod_metadata(kick_client, vod_url)
    except Exception as e:
        logger.warning("Basit metadata cekme hatasi: %s, fallback deneniyor", e)
        return await fetch_vod_metadata(kick_client, vod_url)


def _normalize_vod_metadata(raw: dict[str, Any], vod_url: str) -> dict[str, Any]:
    """Ham VOD metadata'sini normalize et."""
    title = str(raw.get("session_title") or raw.get("title") or "")
    duration_raw = raw.get("duration", 0)
    duration_sec = float(duration_raw) if duration_raw else 3600
    if duration_sec > 86400:
        duration_sec = duration_sec / 1000.0

    category = ""
    categories = raw.get("categories", [])
    if isinstance(categories, list) and categories:
        first = categories[0]
        category = str(first.get("name", "")) if isinstance(first, dict) else str(first)
    elif isinstance(categories, str):
        category = categories

    return {
        "id": raw.get("id", ""),
        "session_title": title,
        "title": title,
        "duration": duration_sec,
        "categories": categories,
        "category": category,
        "start_time": str(raw.get("start_time") or raw.get("created_at", "")),
        "created_at": str(raw.get("created_at", "")),
        "vod_url": vod_url,
    }


async def get_hls_source(vod_url: str) -> Optional[str]:
    """Kick API'den HLS source URL'si al (minimal bandwidth)."""
    try:
        from curl_cffi.requests import Session as CurlSession

        vod_id = extract_vod_id(vod_url)
        if not vod_id:
            return None

        session = CurlSession(impersonate="chrome124")
        try:
            resp = session.get(
                f"https://kick.com/api/v2/video/{vod_id}",
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    # Farkli alanlarda HLS URL'si arayalim
                    source = data.get("source") or data.get("hls_url") or ""
                    if source and ".m3u8" in str(source):
                        return str(source)
                    # Playback URL icin
                    livestream = data.get("livestream", {})
                    if isinstance(livestream, dict):
                        source = livestream.get("playback_url") or ""
                        if source and ".m3u8" in str(source):
                            return str(source)
        finally:
            session.close()

        return None

    except ImportError:
        logger.warning("curl_cffi yuklu degil, HLS source alinamadi")
        return None
    except Exception as e:
        logger.warning("HLS source alma hatasi: %s", e)
        return None
