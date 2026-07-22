"""
Otomatik Kancalama Servisi
───────────────────────────
LLM ile klibin kancalama (hook) noktalarını tespit eder,
stok video servisinden intro/outro/transition bulur,
FFmpeg ile compose eder.

Pipeline:
1. Clip analiz et (clip_analyzer)
2. Hook noktaları için stok video öner
3. Intro/outro/transition indir
4. FFmpeg ile compose et: intro + clip + outro
5. Sonucu data/edited_clips/ klasörüne kaydet
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("auto_hook")

EDITED_DIR = Path("data/edited_clips")
EDITED_DIR.mkdir(parents=True, exist_ok=True)


class AutoHook:
    """
    Otomatik kancalama servisi.
    LLM + stok video + FFmpeg ile klibin başına/sonuna
    dikkat çekici intro/outro ekler.
    """

    def __init__(self):
        self._is_processing = False
        self._results: list[dict] = []

    def is_processing(self) -> bool:
        return self._is_processing

    def get_results(self) -> list[dict]:
        return self._results[-50:]

    async def apply_hook(
        self,
        clip: dict[str, Any],
        add_intro: bool = True,
        add_outro: bool = True,
        add_subtitle: bool = False,
        style: str = "cinematic",
    ) -> dict[str, Any]:
        """
        Tek bir klibe otomatik kancalama uygula.

        1. Clip analiz et
        2. Uygun stok video bul
        3. Intro/outro indir
        4. FFmpeg compose
        """
        from services.clip_analyzer import clip_analyzer
        from services.stock_video_service import stock_video_service

        clip_id = clip.get("clip_id", "unknown")
        clip_url = clip.get("clip_url", clip.get("hls_url", ""))
        title = clip.get("title", "untitled")

        if not clip_url:
            return {"status": "error", "error": "no clip URL", "clip_id": clip_id}

        self._is_processing = True
        result = {
            "clip_id": clip_id,
            "title": title,
            "status": "processing",
            "steps": [],
        }

        try:
            # Step 1: Analiz et
            analysis = await clip_analyzer.analyze_clip(clip)
            result["analysis"] = analysis
            result["steps"].append("analysis_complete")

            intro_url = None
            outro_url = None

            # Step 2: Intro bul
            if add_intro and analysis.get("intro_suggestion"):
                intros = await stock_video_service.get_intro(style=style, limit=3)
                if intros:
                    intro_url = intros[0].get("url")
                    result["intro"] = intros[0]
                    result["steps"].append("intro_found")

            # Step 3: Outro bul
            if add_outro and analysis.get("outro_suggestion"):
                outros = await stock_video_service.get_outro(style="subscribe", limit=3)
                if outros:
                    outro_url = outros[0].get("url")
                    result["outro"] = outros[0]
                    result["steps"].append("outro_found")

            # Step 4: Clip indir (HLS → MP4)
            clip_path = await self._download_clip(clip_url, clip_id)
            if not clip_path:
                result["status"] = "error"
                result["error"] = "Clip indirilemedi"
                return result
            result["steps"].append("clip_downloaded")

            # Step 5: Compose
            output_path = str(EDITED_DIR / f"{clip_id}_hooked.mp4")
            composed = await stock_video_service.compose_with_stock(
                clip_path=clip_path,
                intro_url=intro_url,
                outro_url=outro_url,
                output_path=output_path,
            )
            result["output_path"] = composed
            result["steps"].append("composed")

            # Step 6: Altyazı (opsiyonel)
            if add_subtitle and analysis.get("suggested_edits"):
                subtitle_edits = [
                    e for e in analysis["suggested_edits"]
                    if e.get("type") == "subtitle"
                ]
                if subtitle_edits:
                    result["subtitle_suggestion"] = subtitle_edits[0]
                    result["steps"].append("subtitle_suggested")

            result["status"] = "completed"
            logger.info("Auto-hook completed for %s → %s", clip_id, composed)

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error("Auto-hook failed for %s: %s", clip_id, e)

        finally:
            self._is_processing = False
            self._results.append(result)

        return result

    async def apply_hook_batch(
        self,
        clips: list[dict[str, Any]],
        **kwargs,
    ) -> list[dict[str, Any]]:
        """Toplu kancalama uygula."""
        results = []
        for clip in clips:
            r = await self.apply_hook(clip, **kwargs)
            results.append(r)
        return results

    async def _download_clip(self, url: str, clip_id: str) -> str:
        """Clip indir (HLS veya MP4)."""
        output = EDITED_DIR / f"{clip_id}_raw.mp4"
        if output.exists():
            return str(output)

        # HLS playlist ise
        if url.endswith(".m3u8") or "playlist" in url:
            cmd = [
                "ffmpeg", "-y",
                "-i", url,
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac",
                str(output),
            ]
        else:
            # Direkt MP4
            import httpx
            try:
                async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    output.write_bytes(resp.content)
                    return str(output)
            except Exception as e:
                logger.error("Download failed: %s", e)
                return ""

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error("FFmpeg download failed: %s", stderr.decode()[:300])
                return ""
            return str(output)
        except Exception as e:
            logger.error("Download error: %s", e)
            return ""


# Singleton
auto_hook = AutoHook()
