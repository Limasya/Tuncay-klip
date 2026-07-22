"""
KickBot Clip Collector
──────────────────────
kickbot.com/clips/{username} ve Kick API'den clip'leri toplar.
- KickBot HLS clip URL'lerini parse eder
- Kick API /api/v2/channels/{slug}/clips endpoint'ini kullanır
- state: data/kickbot_clips_state.json
- Periyodik kontrol + manuel refresh
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from shared.utils.json_state import JsonStateStore

logger = logging.getLogger("kickbot_collector")

KICKBOT_STATE_PATH = Path("data/kickbot_clips_state.json")


class KickBotCollector:
    """
    KickBot ve Kick API'den clip toplayan servis.
    kickbot.com clips sayfası SvelteKit SPA olduğu için
    Kick API'yi curl_cffi ile çağırarak clip'leri topluyoruz.
    """

    def __init__(self, username: str = "thetuncay"):
        self._username = username
        self._kick_slug = username
        self._state_store = JsonStateStore(
            KICKBOT_STATE_PATH,
            default_factory=self._default_state,
        )
        self._is_running = False
        self._monitor_task: Optional[asyncio.Task] = None

    @staticmethod
    def _default_state() -> dict:
        return {
            "clips": {},
            "last_sync": None,
            "total_collected": 0,
            "errors": 0,
        }

    async def read_state(self) -> dict:
        return await self._state_store.load()

    async def _write_state(self, state: dict):
        await self._state_store.save(state)

    # ── Kick API Clip Collection ─────────────────────────────────

    async def fetch_clips_from_kick_api(
        self, cursor: int = 0, sort: str = "view", limit: int = 50
    ) -> list[dict[str, Any]]:
        """
        Kick API'den clip'leri çek.
        Endpoint: /api/v2/channels/{slug}/clips?cursor=0&sort=view
        curl_cffi ile Cloudflare bypass.
        """
        url = f"https://kick.com/api/v2/channels/{self._kick_slug}/clips"
        params = {"cursor": cursor, "sort": sort}

        try:
            try:
                from curl_cffi.requests import AsyncSession as CurlAsyncSession
                async with CurlAsyncSession(impersonate="chrome") as sess:
                    resp = await sess.get(url, params=params, timeout=20)
                    data = resp.json()
            except ImportError:
                async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                    resp = await client.get(url, params=params)
                    data = resp.json()

            clips_raw = data.get("clips", data) if isinstance(data, dict) else data
            if isinstance(clips_raw, dict):
                clips_raw = clips_raw.get("clips", [])

            results = []
            for clip in clips_raw[:limit]:
                clip_id = clip.get("id", "")
                clip_url = clip.get("clip_url", "")
                if not clip_id:
                    continue

                hls_url = ""
                if clip_url:
                    hls_url = clip_url
                elif clip.get("video_url"):
                    hls_url = clip["video_url"]

                results.append({
                    "clip_id": str(clip_id),
                    "title": clip.get("title", ""),
                    "slug": clip.get("slug", ""),
                    "clip_url": hls_url,
                    "thumbnail_url": clip.get("thumbnail", ""),
                    "duration": clip.get("duration", 0),
                    "views": clip.get("views", {}).get("count", 0) if isinstance(clip.get("views"), dict) else clip.get("views", 0),
                    "likes": clip.get("likes", {}).get("count", 0) if isinstance(clip.get("likes"), dict) else clip.get("likes", 0),
                    "creator_username": clip.get("creator", {}).get("username", "") if isinstance(clip.get("creator"), dict) else "",
                    "created_at": clip.get("created_at", ""),
                    "source": "kick_api",
                })

            logger.info("Fetched %d clips from Kick API for %s", len(results), self._username)
            return results

        except Exception as e:
            logger.error("Kick API fetch failed for %s: %s", self._username, e)
            return []

    # ── KickBot CDN HLS URL ──────────────────────────────────────

    @staticmethod
    def get_kickbot_hls_url(clip_id: str) -> str:
        """KickBot CDN'den HLS playlist URL'i üret."""
        return f"https://clips.kickbotcdn.com/kickbot-hls/{clip_id}/playlist.m3u8"

    @staticmethod
    def get_kickbot_thumbnail(clip_id: str) -> str:
        """KickBot CDN'den first frame thumbnail URL'i üret."""
        return f"https://clips.kickbotcdn.com/kickbot-hls/{clip_id}/first_frame.jpg"

    # ── Sync Pipeline ────────────────────────────────────────────

    async def sync_clips(self, limit: int = 100) -> dict:
        """
        Kick API'den clip'leri çek ve state'e kaydet.
        Returns: sync sonucu
        """
        state = await self.read_state()
        existing_ids = set(state.get("clips", {}).keys())

        new_clips = await self.fetch_clips_from_kick_api(limit=limit)

        added = 0
        for clip in new_clips:
            cid = clip["clip_id"]
            if cid not in existing_ids:
                clip["hls_url"] = self.get_kickbot_hls_url(cid)
                clip["kickbot_thumbnail"] = self.get_kickbot_thumbnail(cid)
                clip["synced_at"] = datetime.now(timezone.utc).isoformat()
                state["clips"][cid] = clip
                added += 1

        state["last_sync"] = datetime.now(timezone.utc).isoformat()
        state["total_collected"] = len(state["clips"])
        await self._write_state(state)

        logger.info("Sync complete: %d new clips (total: %d)", added, state["total_collected"])
        return {
            "new_clips": added,
            "total": state["total_collected"],
            "last_sync": state["last_sync"],
        }

    # ── Query Methods ────────────────────────────────────────────

    async def get_all_clips(
        self, sort_by: str = "views", limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Tüm clip'leri listele."""
        state = await self.read_state()
        clips = list(state.get("clips", {}).values())

        reverse = True
        if sort_by == "views":
            clips.sort(key=lambda c: c.get("views", 0), reverse=reverse)
        elif sort_by == "likes":
            clips.sort(key=lambda c: c.get("likes", 0), reverse=reverse)
        elif sort_by == "duration":
            clips.sort(key=lambda c: c.get("duration", 0), reverse=reverse)
        elif sort_by == "recent":
            clips.sort(key=lambda c: c.get("created_at", ""), reverse=reverse)

        return clips[offset:offset + limit]

    async def search_clips(self, query: str) -> list[dict[str, Any]]:
        """Clip'lerde ara."""
        state = await self.read_state()
        q = query.lower()
        results = []
        for clip in state.get("clips", {}).values():
            title = clip.get("title", "").lower()
            creator = clip.get("creator_username", "").lower()
            if q in title or q in creator:
                results.append(clip)
        return results

    async def get_clip(self, clip_id: str) -> Optional[dict[str, Any]]:
        """Tek bir clip getir."""
        state = await self.read_state()
        return state.get("clips", {}).get(clip_id)

    async def get_stats(self) -> dict:
        """İstatistikler."""
        state = await self.read_state()
        clips = list(state.get("clips", {}).values())
        total_views = sum(c.get("views", 0) for c in clips)
        total_likes = sum(c.get("likes", 0) for c in clips)
        return {
            "total_clips": len(clips),
            "total_views": total_views,
            "total_likes": total_likes,
            "avg_duration": sum(c.get("duration", 0) for c in clips) / max(len(clips), 1),
            "last_sync": state.get("last_sync"),
            "username": self._username,
        }

    # ── Background Monitor ───────────────────────────────────────

    async def start_monitor(self, interval: int = 300):
        """Arka planda periyodik sync başlat."""
        if self._monitor_task and not self._monitor_task.done():
            return
        self._is_running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval))

    async def stop_monitor(self):
        """Monitorü durdur."""
        self._is_running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self, interval: int):
        """Periyodik sync döngüsü."""
        while self._is_running:
            try:
                await self.sync_clips()
            except Exception as e:
                logger.error("Monitor sync failed: %s", e)
                state = await self.read_state()
                state["errors"] = state.get("errors", 0) + 1
                await self._write_state(state)
            await asyncio.sleep(interval)


# Singleton
kickbot_collector = KickBotCollector()
