"""
Video indirme modulu.
yt-dlp ile Twitch, YouTube, Kick ve diger platformlardan
canli yayin kaydi ve VOD indirme.
"""
import asyncio
import logging
import json
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)


class StreamDownloader:
    """
    yt-dlp tabanlı coklu-platform video/canli yayin indirici.
    Desteklenen platformlar: Twitch, YouTube, Kick, Facebook, vb.
    """

    def __init__(self):
        self._process: Optional[asyncio.subprocess.Process] = None
        self.is_downloading = False

    async def download_live(
        self,
        url: str,
        output_dir: str = None,
        duration: int = None,
        quality: str = "best",
        format_ext: str = "mp4",
    ) -> Optional[str]:
        """
        Canli yayini belirtilen sure boyunca kaydeder.

        Args:
            url: Yayin URL'si (twitch.tv/..., kick.com/..., youtube.com/...)
            output_dir: Cikti dizini
            duration: Kayit suresi (saniye), None = sonsuz
            quality: Video kalitesi (best, 720p, 480p, worst)
            format_ext: Cikti formati (mp4, mkv, webm)

        Returns:
            Indirilen dosyanin yolu veya None
        """
        if not output_dir:
            output_dir = str(RAW_DIR)

        output_template = str(
            Path(output_dir) / f"live_{datetime.now().strftime('%Y%m%d_%H%M%S')}.%(ext)s"
        )

        # Kalite secimi
        format_selector = self._quality_to_format(quality, format_ext)

        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", format_selector,
            "-o", output_template,
            "--no-overwrites",
        ]

        # Sure siniri
        if duration:
            # yt-dlp canli yayinlar icin --download-sections
            cmd.extend(["--download-sections", f"*0-{duration}"])

        cmd.append(url)

        logger.info("Canli yayin indiriliyor: %s", url)
        self.is_downloading = True

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await self._process.communicate()

            if self._process.returncode == 0:
                # Indirilen dosyayi bul
                downloaded = self._find_downloaded_file(output_dir, "live_")
                logger.info("Indirme tamamlandi: %s", downloaded)
                return downloaded
            else:
                logger.error("Indirme hatasi: %s", stderr.decode()[:500])
                return None

        except Exception as e:
            logger.error("Indirme exception: %s", e)
            return None
        finally:
            self.is_downloading = False

    async def download_vod(
        self,
        url: str,
        output_dir: str = None,
        quality: str = "best",
        format_ext: str = "mp4",
    ) -> Optional[str]:
        """
        VOD (Video on Demand) indirir - gecmis yayin kaydi.

        Args:
            url: VOD URL'si
            output_dir: Cikti dizini
            quality: Kalite
            format_ext: Format

        Returns:
            Indirilen dosyanin yolu
        """
        if not output_dir:
            output_dir = str(RAW_DIR)

        output_template = str(
            Path(output_dir) / "%(title)s_%(id)s.%(ext)s"
        )

        format_selector = self._quality_to_format(quality, format_ext)

        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", format_selector,
            "-o", output_template,
            "--no-overwrites",
            url,
        ]

        logger.info("VOD indiriliyor: %s", url)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                downloaded = self._find_downloaded_file(output_dir)
                logger.info("VOD indirme tamamlandi: %s", downloaded)
                return downloaded
            else:
                logger.error("VOD indirme hatasi: %s", stderr.decode()[:500])
                return None

        except Exception as e:
            logger.error("VOD indirme exception: %s", e)
            return None

    async def get_stream_info(self, url: str) -> Optional[Dict]:
        """
        URL'deki yayin/video bilgisini cekmeden indirir.

        Returns:
            {"title": str, "duration": float, "uploader": str, ...}
        """
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-download",
            "--no-playlist",
            url,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await proc.communicate()

            if proc.returncode == 0 and stdout:
                data = json.loads(stdout.decode())
                return {
                    "title": data.get("title", ""),
                    "duration": data.get("duration", 0),
                    "uploader": data.get("uploader", ""),
                    "view_count": data.get("view_count", 0),
                    "description": data.get("description", ""),
                    "thumbnail": data.get("thumbnail", ""),
                    "url": url,
                    "is_live": data.get("is_live", False),
                    "platform": self._detect_platform(url),
                }

        except Exception as e:
            logger.error("Stream info hatasi: %s", e)

        return None

    async def stop_download(self):
        """Aktif indirmeyi durdurur."""
        if self._process:
            self._process.terminate()
            self.is_downloading = False
            logger.info("Indirme durduruldu.")

    def _quality_to_format(self, quality: str, ext: str = "mp4") -> str:
        """Kalite ayarini yt-dlp format selector'e cevirir."""
        quality_map = {
            "best": f"bestvideo[ext={ext}]+bestaudio[ext=m4a]/best[ext={ext}]/best",
            "1080p": f"bestvideo[height<=1080][ext={ext}]+bestaudio/best[height<=1080]",
            "720p": f"bestvideo[height<=720][ext={ext}]+bestaudio/best[height<=720]",
            "480p": f"bestvideo[height<=480][ext={ext}]+bestaudio/best[height<=480]",
            "worst": f"worstvideo[ext={ext}]+worstaudio/worst[ext={ext}]/worst",
        }
        return quality_map.get(quality, quality_map["best"])

    def _detect_platform(self, url: str) -> str:
        """URL'den platform tespit eder."""
        url_lower = url.lower()
        if "twitch.tv" in url_lower:
            return "twitch"
        elif "youtube.com" in url_lower or "youtu.be" in url_lower:
            return "youtube"
        elif "kick.com" in url_lower:
            return "kick"
        elif "facebook.com" in url_lower:
            return "facebook"
        return "unknown"

    def _find_downloaded_file(self, directory: str, prefix: str = "") -> Optional[str]:
        """Dizindeki en yeni indirilmis dosyayi bulur."""
        p = Path(directory)
        files = sorted(p.glob(f"{prefix}*"), key=lambda f: f.stat().st_mtime, reverse=True)
        return str(files[0]) if files else None


# Singleton
stream_downloader = StreamDownloader()
