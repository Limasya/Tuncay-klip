"""
Stok Video Servisi — Pexels + Pixabay Ücretsiz Stok Video Arama
───────────────────────────────────────────────────────────────
- Pexels API: 200 req/h, 20k/month (ücretsiz)
- Pixabay API: istek limiti yok (ücretsiz)
- Kategoriler: intro, outro, transition, overlay, background, effect
- Otomatik indirme ve cache: data/stock_videos_cache.json
- FFmpeg ile embed: clip başına/sonuna stok video ekle
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("stock_video_service")

STOCK_CACHE_PATH = Path("data/stock_videos_cache.json")
STOCK_DIR = Path("data/stock_videos")
STOCK_DIR.mkdir(parents=True, exist_ok=True)

PRESET_CATEGORIES = {
    "hook": [
        "dramatic reveal", "shocking moment", "pattern interrupt",
        "curiosity gap visual", "bold statement overlay", "suspense building",
    ],
    "reaction": [
        "gaming reaction", "surprise reaction", "excited face",
        "shocked expression", "celebration moment",
    ],
    "transition": [
        "glitch transition", "light leak", "smoke transition",
        "particle transition", "zoom transition", "whip pan",
    ],
    "overlay": [
        "fire overlay", "particles overlay", "light streak",
        "lens flare", "sparkle overlay", "neon glow",
    ],
    "background": [
        "abstract background", "loop background", "gradient background",
        "tech background", "gaming background", "cyberpunk background",
    ],
    "effect": [
        "explosion effect", "screen shake", "speed lines",
        "dramatic zoom", "impact frame", "flash effect",
    ],
}


class StockVideoService:
    """
    Pexels + Pixabay'dan stok video arayan ve indiren servis.
    Cache-first: daha önce aranmış sorguları tekrar sormaz.
    """

    def __init__(self):
        self._pexels_key = os.environ.get("PEXELS_API_KEY", "")
        self._pixabay_key = os.environ.get("PIXABAY_API_KEY", "")
        self._cache: dict[str, Any] = {}
        self._load_cache()
        self._rate_limiter_pexels = 0.0
        self._rate_limiter_pixabay = 0.0

    def _load_cache(self):
        if STOCK_CACHE_PATH.exists():
            try:
                self._cache = json.loads(STOCK_CACHE_PATH.read_text(encoding="utf-8"))
            except Exception:
                self._cache = {}

    def _save_cache(self):
        try:
            STOCK_CACHE_PATH.write_text(
                json.dumps(self._cache, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Cache save failed: %s", e)

    def _cache_key(self, source: str, query: str) -> str:
        return f"{source}:{query.lower().strip()}"

    # ── Pexels API ───────────────────────────────────────────────

    async def _search_pexels(
        self, query: str, per_page: int = 5, min_duration: int = 3, max_duration: int = 15
    ) -> list[dict[str, Any]]:
        """Pexels'te video ara."""
        if not self._pexels_key:
            return []

        import httpx

        url = "https://api.pexels.com/videos/search"
        headers = {"Authorization": self._pexels_key}
        params = {
            "query": query,
            "per_page": per_page,
            "size": "medium",
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code == 429:
                    logger.warning("Pexels rate limited, waiting...")
                    await asyncio.sleep(5)
                    return []
                resp.raise_for_status()
                data = resp.json()

            results = []
            for video in data.get("videos", []):
                duration = video.get("duration", 0)
                if not (min_duration <= duration <= max_duration):
                    continue

                files = video.get("video_files", [])
                if not files:
                    continue

                hd_files = [f for f in files if f.get("quality") == "hd"]
                chosen = hd_files[0] if hd_files else files[0]

                results.append({
                    "source": "pexels",
                    "id": video.get("id"),
                    "url": chosen.get("link", ""),
                    "preview_url": video.get("video_pictures", [{}])[0].get("picture", ""),
                    "duration": duration,
                    "width": chosen.get("width", 0),
                    "height": chosen.get("height", 0),
                    "fps": chosen.get("fps", 30),
                    "query": query,
                })
            return results

        except Exception as e:
            logger.warning("Pexels search failed for '%s': %s", query, e)
            return []

    # ── Pixabay API ──────────────────────────────────────────────

    async def _search_pixabay(
        self, query: str, per_page: int = 5, min_duration: int = 3, max_duration: int = 15
    ) -> list[dict[str, Any]]:
        """Pixabay'de video ara."""
        if not self._pixabay_key:
            return []

        import httpx

        url = "https://pixabay.com/api/videos/"
        params = {
            "key": self._pixabay_key,
            "q": query,
            "per_page": per_page,
            "min_width": 640,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 429:
                    logger.warning("Pixabay rate limited")
                    return []
                resp.raise_for_status()
                data = resp.json()

            results = []
            for hit in data.get("hits", []):
                videos = hit.get("videos", {})
                large = videos.get("large", videos.get("medium", {}))
                duration = hit.get("duration", 0)

                if not (min_duration <= duration <= max_duration):
                    continue

                results.append({
                    "source": "pixabay",
                    "id": hit.get("id"),
                    "url": large.get("url", ""),
                    "preview_url": hit.get("picture_id", ""),
                    "duration": duration,
                    "width": large.get("width", 0),
                    "height": large.get("height", 0),
                    "fps": 30,
                    "query": query,
                    "tags": hit.get("tags", ""),
                })
            return results

        except Exception as e:
            logger.warning("Pixabay search failed for '%s': %s", query, e)
            return []

    # ── Public API ───────────────────────────────────────────────

    async def search_videos(
        self, query: str, category: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """
        Stok video ara (Pexels + Pixabay birleşik).
        Cache-first: daha önce aranmışsa cache'den dön.
        """
        cache_key = self._cache_key("all", query)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if time.time() - cached.get("ts", 0) < 86400:
                logger.debug("Cache hit for '%s'", query)
                return cached.get("results", [])[:limit]

        pexels_task = self._search_pexels(query)
        pixabay_task = self._search_pixabay(query)

        pexels_results, pixabay_results = await asyncio.gather(
            pexels_task, pixabay_task, return_exceptions=True
        )

        if isinstance(pexels_results, Exception):
            logger.warning("Pexels failed: %s", pexels_results)
            pexels_results = []
        if isinstance(pixabay_results, Exception):
            logger.warning("Pixabay failed: %s", pixabay_results)
            pixabay_results = []

        all_results = pexels_results + pixabay_results
        all_results.sort(key=lambda x: x.get("duration", 0))

        self._cache[cache_key] = {
            "ts": time.time(),
            "query": query,
            "results": all_results,
        }
        self._save_cache()

        return all_results[:limit]

    async def search_category(
        self, category: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """
        Kategori bazlı stok video ara.
        preset kategoriler: intro, outro, transition, overlay, background
        """
        queries = PRESET_CATEGORIES.get(category, [category])
        import random
        query = random.choice(queries)
        return await self.search_videos(query, category=category, limit=limit)

    async def get_intro(self, style: str = "cinematic", limit: int = 3) -> list[dict]:
        """Intro stok videoları getir."""
        return await self.search_videos(f"{style} intro logo reveal", limit=limit)

    async def get_outro(self, style: str = "subscribe", limit: int = 3) -> list[dict]:
        """Outro stok videoları getir."""
        return await self.search_videos(f"{style} outro end screen", limit=limit)

    async def get_transition(self, style: str = "glitch", limit: int = 3) -> list[dict]:
        """Transition stok videoları getir."""
        return await self.search_videos(f"{style} transition effect", limit=limit)

    async def get_overlay(self, style: str = "particles", limit: int = 3) -> list[dict]:
        """Overlay stok videoları getir."""
        return await self.search_videos(f"{style} overlay effect transparent", limit=limit)

    async def download_video(self, url: str, filename: str | None = None) -> str:
        """
        Stok video indir ve yerel path dön.
        Returns: indirilen dosya yolu
        """
        if not filename:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
            filename = f"stock_{url_hash}.mp4"

        output_path = STOCK_DIR / filename
        if output_path.exists():
            return str(output_path)

        import httpx

        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                output_path.write_bytes(resp.content)
                logger.info("Downloaded stock video: %s (%d bytes)", filename, len(resp.content))
                return str(output_path)
        except Exception as e:
            logger.error("Download failed for %s: %s", url, e)
            return ""

    async def compose_with_stock(
        self,
        clip_path: str,
        intro_url: str | None = None,
        outro_url: str | None = None,
        output_path: str | None = None,
    ) -> str:
        """
        Clip'in başına/sonuna stok video ekle (FFmpeg concat).
        Returns: compose edilmiş video path
        """
        if not output_path:
            base = Path(clip_path).stem
            output_path = str(EDITED_DIR / f"{base}_composed.mp4")

        parts = []

        if intro_url:
            intro_path = await self.download_video(intro_url, f"intro_{hashlib.md5(intro_url.encode()).hexdigest()[:8]}.mp4")
            if intro_path:
                parts.append(intro_path)

        parts.append(clip_path)

        if outro_url:
            outro_path = await self.download_video(outro_url, f"outro_{hashlib.md5(outro_url.encode()).hexdigest()[:8]}.mp4")
            if outro_path:
                parts.append(outro_path)

        if len(parts) < 2:
            logger.info("No stock videos to compose, returning original")
            return clip_path

        concat_file = Path(output_path).with_suffix(".txt")
        with open(concat_file, "w") as f:
            for p in parts:
                f.write(f"file '{os.path.abspath(p)}'\n")

        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac",
            output_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error("FFmpeg concat failed: %s", stderr.decode()[:300])
                return clip_path
            logger.info("Composed video: %s", output_path)
            return output_path
        except Exception as e:
            logger.error("Compose error: %s", e)
            return clip_path

    def get_stats(self) -> dict:
        """Stok video istatistikleri."""
        return {
            "cache_entries": len(self._cache),
            "pexels_configured": bool(self._pexels_key),
            "pixabay_configured": bool(self._pixabay_key),
            "downloaded_videos": len(list(STOCK_DIR.glob("*.mp4"))),
            "categories": list(PRESET_CATEGORIES.keys()),
        }


# Singleton
stock_video_service = StockVideoService()
