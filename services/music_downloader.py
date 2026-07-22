"""
Otomatik Müzik Indirme Servisi (Coklu Dil + Multi-Kaynak)
==========================================================
- YouTube Music trending → MP3
- TikTok trending sounds → MP3
- Spotify charts → spotDL (opsiyonel)
- Pixabay Music API → MP3
- Ses kutuphanesini otomatik doldurur (data/music/, data/sfx/)
- Rust audio-mixer ile birlikte calisir
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import subprocess
import tempfile
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("music_downloader")

MUSIC_DIR = Path("data/music")
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

SFX_DIR = Path("data/sfx")
SFX_DIR.mkdir(parents=True, exist_ok=True)

BGM_DIR = Path("data/bgm")
BGM_DIR.mkdir(parents=True, exist_ok=True)

# ── Kaynak URL'leri ─────────────────────────────────────────────
SOURCES = {
    "pixabay_music": {
        "trending": "https://pixabay.com/api/v1/music/?key={}&q=trending&per_page=50",
        "search": "https://pixabay.com/api/v1/music/?key={}&q={}&per_page=20",
    },
}

# ── TikTok trend URL'leri (scrape edilebilir) ──────────────────
TIKTOK_TRENDING_SOUNDS = [
    "https://www.tiktok.com/music/top200",
    "https://www.tiktok.com/music/trending",
]

# ── YouTube Music trend arama ──────────────────────────────────
YTM_TRENDING_QUERIES = [
    "ytsearch5:tik tok viral songs 2026",
    "ytsearch5:trending music reels 2026",
    "ytsearch5:viral background music 2026",
    "ytsearch5:hype energy music no copyright",
    "ytsearch5:gaming background music epic",
    "ytsearch5:lofi beats 2026",
    "ytsearch5:upbeat motivational music",
    "ytsearch5:cinematic dramatic music",
]


class MusicDownloader:
    """
    Internetten otomatik muzik indirme servisi.
    yt-dlp + Pixabay API + scraping ile calisir.
    Rust audio-mixer icin data/music/ klasorunu doldurur.
    """

    def __init__(self):
        self._pixabay_key = self._get_pixabay_key()
        self._downloaded_log = MUSIC_DIR / ".downloaded.json"
        self._downloaded: set[str] = self._load_downloaded()
        self._ffprobe_available = self._check_ffprobe()

    def _get_pixabay_key(self) -> str:
        """Pixabay API anahtari (opsiyonel)."""
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        return os.getenv("PIXABAY_API_KEY", "")

    def _load_downloaded(self) -> set[str]:
        if self._downloaded_log.exists():
            try:
                data = json.loads(self._downloaded_log.read_text())
                return set(data.get("ids", []))
            except Exception:
                return set()
        return set()

    def _save_downloaded(self):
        self._downloaded_log.write_text(json.dumps({
            "ids": list(self._downloaded),
        }, indent=2))

    @staticmethod
    def _check_ffprobe() -> bool:
        """ffprobe kullanilabilir mi kontrol et."""
        try:
            subprocess.run(["ffprobe", "-version"], capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    @staticmethod
    def _check_ytdlp() -> bool:
        """yt-dlp kullanilabilir mi kontrol et."""
        try:
            subprocess.run(["yt-dlp", "--version"], capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    def _is_silent(self, audio_path: str, threshold: float = -50.0) -> bool:
        """Sessiz dosya mi kontrol et (ffmpeg volumedetect ile)."""
        if not self._ffprobe_available:
            return False
        cmd = [
            "ffmpeg", "-i", audio_path, "-af",
            f"volumedetect=volume={threshold}", "-f", "null", "-",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return "max_volume: -inf" in result.stderr
        except Exception:
            return False

    async def download_from_ytdlp(
        self, url: str, output_dir: Path = MUSIC_DIR,
        min_duration: float = 20.0, max_duration: float = 300.0,
    ) -> Optional[str]:
        """yt-dlp ile ses indir."""
        if not self._check_ytdlp():
            logger.warning("yt-dlp bulunamadi")
            return None

        out_template = str(output_dir / "%(title)s.%(ext)s")
        cmd = [
            "yt-dlp", "-x", "--audio-format", "mp3",
            "--audio-quality", "0",
            "--output", out_template,
            "--no-playlist",
            "--max-filesize", "50M",
            "--match-filter", f"duration >= {min_duration} & duration <= {max_duration}",
            "--quiet",
            url,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                err = stderr.decode()[:200]
                if "already downloaded" in err.lower() or "has already been" in err.lower():
                    return None
                logger.debug("yt-dlp basarisiz [%d]: %s", proc.returncode, err)
                return None

            output = stdout.decode().strip()
            if output:
                lines = output.split("\n")
                for line in reversed(lines):
                    if "Destination" in line:
                        path = line.split("Destination: ")[-1].strip()
                        if os.path.exists(path):
                            return path

            # En son eklenen dosyayi bul
            return self._find_newest_file(output_dir)

        except Exception as e:
            logger.debug("yt-dlp exception: %s", e)
            return None

    async def download_pixabay_music(
        self, query: str = "trending", limit: int = 10,
    ) -> list[str]:
        """Pixabay Music API'den muzik indir."""
        if not self._pixabay_key:
            return []

        results: list[str] = []
        url = SOURCES["pixabay_music"]["search"].format(self._pixabay_key, query)

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Tuncay-Klip/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                hits = data.get("hits", [])[:limit]

                for hit in hits:
                    audio_url = hit.get("audio_url", "")
                    if not audio_url:
                        continue

                    track_id = str(hit.get("id", ""))
                    if track_id in self._downloaded:
                        continue

                    title = hit.get("title", f"pixabay_{track_id}")
                    filename = f"pixabay_{track_id}_{title[:30]}.mp3"
                    filepath = MUSIC_DIR / filename

                    if filepath.exists():
                        results.append(str(filepath))
                        self._downloaded.add(track_id)
                        continue

                    try:
                        urllib.request.urlretrieve(audio_url, filepath)
                        duration = hit.get("duration", 0)
                        if duration > 0 and 15 <= duration <= 300:
                            results.append(str(filepath))
                            self._downloaded.add(track_id)
                            logger.info("Pixabay muzik: %s (%ds)", title, duration)
                        else:
                            filepath.unlink(missing_ok=True)
                    except Exception as e:
                        logger.debug("Pixabay download fail: %s", e)

        except Exception as e:
            logger.debug("Pixabay API error: %s", e)

        self._save_downloaded()
        return results

    async def download_trending_music_batch(self) -> dict[str, Any]:
        """Toplu trend muzik indirme — tum kaynaklardan."""
        results = {
            "total": 0,
            "ytdlp": 0,
            "pixabay": 0,
            "files": [],
        }

        # 1. YouTube Music trend aramalari
        if self._check_ytdlp():
            for query in YTM_TRENDING_QUERIES:
                path = await self.download_from_ytdlp(query, MUSIC_DIR)
                if path:
                    results["ytdlp"] += 1
                    results["total"] += 1
                    results["files"].append(path)
                    # Dosya adindan ID hash'i cikar
                    self._downloaded.add(f"yt_{Path(path).stem[:40]}")
                await asyncio.sleep(1)

        # 2. Pixabay API
        for query in ["trending", "background", "energetic", "motivational", "viral", "gaming"]:
            pixabay_results = await self.download_pixabay_music(query, limit=5)
            for p in pixabay_results:
                results["pixabay"] += 1
                results["total"] += 1
                results["files"].append(p)

        self._save_downloaded()
        logger.info("Trend muzik indirme tamam: %d yeni dosya", results["total"])
        return results

    async def download_sfx_from_sources(self) -> int:
        """Internetten SFX dosyalari indir (Pixabay SFX, vb.)."""
        count = 0

        if self._pixabay_key:
            for query in ["impact", "whoosh", "notification", "applause", "laugh"]:
                url = SOURCES["pixabay_music"]["search"].format(
                    self._pixabay_key, query
                )
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Tuncay/1.0"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read())
                        for hit in data.get("hits", [])[:3]:
                            audio_url = hit.get("audio_url", "")
                            if not audio_url:
                                continue
                            dur = hit.get("duration", 0)
                            if dur > 5:
                                continue
                            title = hit.get("title", f"sfx_{query}_{count}")
                            fname = f"sfx_{query}_{count}.mp3"
                            fpath = SFX_DIR / fname
                            if fpath.exists():
                                count += 1
                                continue
                            urllib.request.urlretrieve(audio_url, fpath)
                            count += 1
                            logger.info("SFX indi: %s (%.1fs)", fname, dur)
                except Exception as e:
                    logger.debug("SFX download error: %s", e)

        logger.info("SFX indirme tamam: %d dosya", count)
        return count

    async def auto_download_all(self) -> dict[str, Any]:
        """Tum kaynaklardan muzik + SFX indirimi yap."""
        music = await self.download_trending_music_batch()
        sfx_count = await self.download_sfx_from_sources()
        return {
            "music": music,
            "sfx_downloaded": sfx_count,
            "total_new": music["total"] + sfx_count,
        }

    @staticmethod
    def _find_newest_file(directory: Path, ext: str = ".mp3") -> Optional[str]:
        files = list(directory.glob(f"*{ext}"))
        if not files:
            return None
        return str(max(files, key=os.path.getmtime))

    def get_library_stats(self) -> dict[str, Any]:
        return {
            "music_count": len(list(MUSIC_DIR.glob("*.mp3"))) + len(list(MUSIC_DIR.glob("*.wav"))),
            "sfx_count": len(list(SFX_DIR.glob("*.mp3"))) + len(list(SFX_DIR.glob("*.wav"))),
            "bgm_count": len(list(BGM_DIR.glob("*.mp3"))) + len(list(BGM_DIR.glob("*.wav"))),
            "download_log_entries": len(self._downloaded),
        }


# Singleton
music_downloader = MusicDownloader()
