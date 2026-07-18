"""
Kick Public Clips Collector
───────────────────────────
Kick kanalindaki (thetuncay)公众clip'leri toplar ve analiz eder.
- Canli yayinda: Yeni clip'leri takip eder
- Yayin disinda: Eski clip'leri tarar
- Her clip'i kaydeder ve metadata saklar
- Periyodik olarak yeni clip'leri kontrol eder

ASLA VOD indirmez, sadece clip metadata'sini toplar.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config import get_settings
from services.kick_api import kick_service
from shared.utils.json_state import JsonStateStore

logger = logging.getLogger("kick_clips_collector")


class KickClipsCollector:
    """Kick公众clip'leri toplayan servis."""

    def __init__(
        self,
        state_path: str | Path | None = None,
        check_interval: int = 120,
    ):
        self._settings = get_settings()
        self._kick = kick_service
        self._state_store = JsonStateStore(
            state_path or "data/kick_clips_state.json",
            default_factory=self._default_state,
        )
        self._check_interval = check_interval
        self._monitor_task: Optional[asyncio.Task] = None
        self._is_running = False
        self._stats = {
            "total_clips_collected": 0,
            "new_clips_this_session": 0,
            "last_check": None,
            "errors": 0,
        }

    async def start(self) -> bool:
        """Collector'u baslat."""
        if self._is_running:
            return False

        self._is_running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Kick Clips Collector basladi (interval=%ds)", self._check_interval)
        return True

    async def stop(self):
        """Collector'u durdur."""
        self._is_running = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        self._monitor_task = None
        logger.info("Kick Clips Collector durduruldu")

    async def _monitor_loop(self):
        """Ana dongu - periyodik clip kontrolu."""
        while self._is_running:
            try:
                await self._check_new_clips()
            except Exception as e:
                logger.error("Clip kontrolu hatasi: %s", e)
                self._stats["errors"] += 1
            await asyncio.sleep(self._check_interval)

    async def _check_new_clips(self):
        """Yeni clip'leri kontrol et ve kaydet."""
        self._stats["last_check"] = datetime.now(timezone.utc).isoformat()

        state = await self._read_state()
        known_ids = set(state.get("known_clip_ids", []))

        # Kick API'den公众clip'leri cek
        clips = await self._kick.list_channel_clips(limit=50, sort="newest")

        new_clips = []
        for clip in clips:
            clip_id = clip.get("clip_id", "")
            if clip_id and clip_id not in known_ids:
                new_clips.append(clip)
                known_ids.add(clip_id)

        if new_clips:
            logger.info("Yeni clip bulundu: %d adet", len(new_clips))

            # State'i guncelle
            for clip in new_clips:
                clip_id = clip["clip_id"]
                state["clips"][clip_id] = {
                    **clip,
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                    "analyzed": False,
                    "downloaded": False,
                }

            state["known_clip_ids"] = list(known_ids)
            state["total_clips"] = len(state["clips"])
            state["last_check"] = self._stats["last_check"]
            await self._write_state(state)

            self._stats["total_clips_collected"] = len(state["clips"])
            self._stats["new_clips_this_session"] += len(new_clips)

            # Event bus ile bildir
            try:
                from shared.event_bus import get_event_bus
                bus = get_event_bus()
                await bus.publish("kick.clip.discovered", {
                    "count": len(new_clips),
                    "clips": [{"clip_id": c["clip_id"], "title": c.get("title", "")} for c in new_clips[:5]],
                })
            except Exception as e:
                logger.debug("kick.clip.discovered event yayınlanamadı: %s", e)
        else:
            logger.debug("Yeni clip bulunamadi (toplam: %d)", len(known_ids))

    async def collect_all(self, limit: int = 100) -> dict[str, Any]:
        """Tum公众clip'leri topla ve rapor olustur."""
        state = await self._read_state()
        known_ids = set(state.get("known_clip_ids", []))

        all_clips = []
        page = 1
        while len(all_clips) < limit:
            clips = await self._kick.list_channel_clips(limit=50, sort="newest")
            if not clips:
                break
            all_clips.extend(clips)
            page += 1
            if page > 5:
                break

        new_clips = []
        for clip in all_clips:
            clip_id = clip.get("clip_id", "")
            if clip_id and clip_id not in known_ids:
                new_clips.append(clip)
                known_ids.add(clip_id)
                state["clips"][clip_id] = {
                    **clip,
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                    "analyzed": False,
                    "downloaded": False,
                }

        state["known_clip_ids"] = list(known_ids)
        state["total_clips"] = len(state["clips"])
        await self._write_state(state)

        self._stats["total_clips_collected"] = len(state["clips"])

        return {
            "status": "completed",
            "total_discovered": len(all_clips),
            "new_clips": len(new_clips),
            "known_clips": len(known_ids),
            "clips": [
                {
                    "clip_id": c["clip_id"],
                    "title": c.get("title", ""),
                    "creator": c.get("creator_username", ""),
                    "views": c.get("views", 0),
                    "duration": c.get("duration", 0),
                }
                for c in new_clips[:20]
            ],
        }

    async def get_top_clips(self, limit: int = 10, sort_by: str = "views") -> list[dict[str, Any]]:
        """En populer clip'leri dondur."""
        state = await self._read_state()
        clips = list(state.get("clips", {}).values())

        if sort_by == "views":
            clips.sort(key=lambda x: x.get("views", 0), reverse=True)
        elif sort_by == "likes":
            clips.sort(key=lambda x: x.get("likes", 0), reverse=True)
        elif sort_by == "recent":
            clips.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return clips[:limit]

    async def search_clips(self, query: str) -> list[dict[str, Any]]:
        """Clip'ler arasinda ara."""
        state = await self._read_state()
        query_lower = query.lower()
        results = []

        for clip in state.get("clips", {}).values():
            title = clip.get("title", "").lower()
            creator = clip.get("creator_username", "").lower()
            if query_lower in title or query_lower in creator:
                results.append(clip)

        return results

    async def get_clip_stats(self) -> dict[str, Any]:
        """Clip istatistiklerini dondur."""
        state = await self._read_state()
        clips = state.get("clips", {})

        if not clips:
            return {
                "total_clips": 0,
                "total_views": 0,
                "total_likes": 0,
                "avg_duration": 0,
                "top_creators": [],
            }

        total_views = sum(c.get("views", 0) for c in clips.values())
        total_likes = sum(c.get("likes", 0) for c in clips.values())
        avg_duration = sum(c.get("duration", 0) for c in clips.values()) / len(clips)

        # Top creators
        creator_counts: dict[str, int] = {}
        for c in clips.values():
            creator = c.get("creator_username", "unknown")
            creator_counts[creator] = creator_counts.get(creator, 0) + 1
        top_creators = sorted(creator_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "total_clips": len(clips),
            "total_views": total_views,
            "total_likes": total_likes,
            "avg_duration": round(avg_duration, 1),
            "top_creators": [{"name": name, "count": count} for name, count in top_creators],
        }

    async def get_status(self) -> dict[str, Any]:
        """Collector durumunu dondur."""
        return {
            "running": self._is_running,
            "channel": self._settings.kick_channel_slug,
            "channel_url": f"https://kick.com/{self._settings.kick_channel_slug}",
            "check_interval": self._check_interval,
            "stats": self._stats.copy(),
            "state_file": str(self._state_store.path),
        }

    # --- State Management ---
    def _default_state(self) -> dict[str, Any]:
        return {
            "channel": self._settings.kick_channel_slug,
            "known_clip_ids": [],
            "clips": {},
            "total_clips": 0,
            "last_check": None,
            "updated_at": None,
        }

    async def _read_state(self) -> dict[str, Any]:
        state = await self._state_store.load()
        if not isinstance(state, dict):
            return self._default_state()
        if state.get("channel") != self._settings.kick_channel_slug:
            return self._default_state()
        return state

    async def _write_state(self, state: dict[str, Any]) -> None:
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self._state_store.save(state)


# Singleton
kick_clips_collector = KickClipsCollector()
