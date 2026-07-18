"""
VOD Indirme Servisi - Coklu Strateji
─────────────────────────────────────
Kick VOD'larini indirmek icin birden fazla strateji destekler:
  1. curl_cffi + ffmpeg  — Cloudflare bypass, Kick icin birincil yontem
  2. yt-dlp             — YouTube/Twitch icin, Kick'te bazen basarisiz
  3. Direkt indirme     — M3U8/MP4 linkleri icin

Her strateji bagimsiz olarak devre disi birakilabilir.
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Callable

try:
    import yt_dlp
    _YT_DLP_AVAILABLE = True
except ImportError:
    _YT_DLP_AVAILABLE = False

try:
    from curl_cffi.requests import Session as CurlSession
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    _CURL_CFFI_AVAILABLE = False

logger = logging.getLogger("youtube_downloader")


def _resolve_ffmpeg_path() -> Optional[str]:
    """Find ffmpeg binary, including common post-install locations on Windows."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        search_roots = []
        if local_app_data:
            search_roots.append(Path(local_app_data) / "Microsoft" / "WinGet" / "Packages")
            search_roots.append(Path(local_app_data) / "Programs")
        for root in search_roots:
            if not root.exists():
                continue
            for match in root.rglob("ffmpeg.exe"):
                if match.parent.name == "bin":
                    return str(match)
    return None


_FFMPEG_PATH: Optional[str] = _resolve_ffmpeg_path()

if _FFMPEG_PATH:
    _ffmpeg_dir = str(Path(_FFMPEG_PATH).parent)
    if _ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")


class DownloadStrategy:
    """Indirme stratejisi base class."""
    name: str = "base"

    def __init__(self, download_dir: Path):
        self.download_dir = download_dir

    def is_available(self) -> bool:
        return False

    async def download(self, url: str, output_name: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError


class CurlCffiFfmpegStrategy(DownloadStrategy):
    """curl_cffi ile Kick API'den kaynak URL al, ffmpeg ile indir."""
    name = "curl_cffi+ffmpeg"

    def is_available(self) -> bool:
        return _CURL_CFFI_AVAILABLE

    def _extract_source_url(self, api_url: str, target_slug: str) -> Optional[Dict[str, Any]]:
        try:
            session = CurlSession(impersonate="chrome124")
            resp = session.get(api_url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data") or data.get("videos") or []
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_slug = str(item.get("slug") or "")
                item_id = str(item.get("id") or "")
                if item_slug == target_slug or item_id == target_slug:
                    source = item.get("source", "")
                    title = item.get("session_title") or item.get("title") or "vod"
                    duration = item.get("duration") or 0
                    if source:
                        return {"source_url": source, "title": title, "duration": duration}
            logger.debug("No matching VOD found for slug=%s", target_slug)
            return None
        except Exception as exc:
            logger.debug("curl_cffi API fetch failed: %s", exc)
            return None

    def _validate_mp4(self, file_path: str) -> dict:
        """ffprobe ile MP4 dosyasini dogrula."""
        ffmpeg_bin = _FFMPEG_PATH or "ffmpeg"
        ffprobe_bin = ffmpeg_bin.replace("ffmpeg", "ffprobe") if "ffmpeg" in ffmpeg_bin else "ffprobe"
        try:
            cmd = [
                ffprobe_bin, "-v", "quiet",
                "-show_entries", "format=duration,size:stream=codec_type,codec_name",
                "-of", "json", file_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return {"valid": False, "error": f"ffprobe failed: {result.stderr[:200]}"}
            import json
            probe = json.loads(result.stdout)
            streams = probe.get("streams", [])
            fmt = probe.get("format", {})
            duration = float(fmt.get("duration", 0))
            size = int(fmt.get("size", 0))
            has_video = any(s.get("codec_type") == "video" for s in streams)
            has_audio = any(s.get("codec_type") == "audio" for s in streams)
            if duration <= 0:
                return {"valid": False, "error": "zero duration"}
            if not has_video:
                return {"valid": False, "error": "no video stream"}
            if size < 1024 * 1024:
                return {"valid": False, "error": f"file too small ({size} bytes)"}
            return {"valid": True, "duration": duration, "size": size, "has_audio": has_audio}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    def _download_ffmpeg(self, source_url: str, output_path: str) -> bool:
        ffmpeg_bin = _FFMPEG_PATH or "ffmpeg"
        try:
            cmd = [
                ffmpeg_bin, "-y",
                "-headers", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36\r\nReferer: https://kick.com/\r\n",
                "-i", source_url,
                "-c", "copy",
                "-movflags", "+faststart",
                output_path,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=3600,
            )
            if result.returncode != 0:
                logger.warning("ffmpeg download failed (code %d): %s", result.returncode, result.stderr[-500:] if result.stderr else "")
                if Path(output_path).exists():
                    Path(output_path).unlink(missing_ok=True)
                return False
            if not Path(output_path).exists():
                return False
            validation = self._validate_mp4(output_path)
            if not validation.get("valid"):
                logger.warning("Downloaded MP4 invalid: %s — deleting", validation.get("error"))
                Path(output_path).unlink(missing_ok=True)
                return False
            logger.info("MP4 validated: duration=%.1fs, has_audio=%s", validation.get("duration", 0), validation.get("has_audio"))
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("ffmpeg download failed: %s", exc)
            if Path(output_path).exists():
                Path(output_path).unlink(missing_ok=True)
            return False

    async def download(self, url: str, output_name: Optional[str] = None) -> Dict[str, Any]:
        from config import get_settings
        settings = get_settings()
        slug = settings.kick_channel_slug

        video_slug = url.rstrip("/").split("/")[-1]
        api_url = f"https://kick.com/api/v2/channels/{slug}/videos?limit=50&sort=date"

        result = await asyncio.to_thread(self._extract_source_url, api_url, video_slug)
        if not result or not result.get("source_url"):
            return {"error": "curl_cffi: Kick API kaynak URL alinamadi"}

        source_url = result["source_url"]
        title = output_name or result["title"]
        safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title).strip()[:80]
        output_path = str(self.download_dir / f"{safe_title}.mp4")

        success = await asyncio.to_thread(self._download_ffmpeg, source_url, output_path)
        if not success:
            return {"error": "curl_cffi: ffmpeg indirme basarisiz"}

        return {
            "success": True,
            "title": title,
            "file_path": output_path,
            "duration": result.get("duration", 0),
        }


class YtDlpStrategy(DownloadStrategy):
    """yt-dlp ile indirme — YouTube/Twitch icin ideal, Kick'te bazen calisir."""
    name = "yt-dlp"

    def is_available(self) -> bool:
        return _YT_DLP_AVAILABLE

    def _download_sync(self, url: str, output_name: Optional[str] = None) -> Dict[str, Any]:
        output_template = str(self.download_dir / "%(title)s_%(id)s.%(ext)s")
        if output_name:
            output_template = str(self.download_dir / f"{output_name}.%(ext)s")

        ydl_opts = {
            "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": output_template,
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "extractor_retries": 3,
            "retries": 3,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                if not info_dict:
                    return {"error": "yt-dlp: bilgi alinamadi"}
                file_path = ydl.prepare_filename(info_dict)
                path_obj = Path(file_path)
                if not path_obj.exists():
                    possible_paths = list(self.download_dir.glob(f"{path_obj.stem}.*"))
                    if possible_paths:
                        file_path = str(possible_paths[0])
                if not Path(file_path).exists():
                    return {"error": "yt-dlp: dosya olusturulamadi"}
                validator = CurlCffiFfmpegStrategy(self.download_dir)
                validation = validator._validate_mp4(file_path)
                if not validation.get("valid"):
                    Path(file_path).unlink(missing_ok=True)
                    return {"error": f"yt-dlp: MP4 gecersiz — {validation.get('error')}"}
                return {
                    "success": True,
                    "title": info_dict.get("title", "Unknown"),
                    "file_path": file_path,
                    "duration": validation.get("duration", info_dict.get("duration", 0)),
                }
        except Exception as e:
            return {"error": f"yt-dlp: {e}"}

    async def download(self, url: str, output_name: Optional[str] = None) -> Dict[str, Any]:
        return await asyncio.to_thread(self._download_sync, url, output_name)


class DirectUrlStrategy(DownloadStrategy):
    """Direkt M3U8/MP4 URL'sinden ffmpeg ile indirme."""
    name = "direct-ffmpeg"

    def is_available(self) -> bool:
        return True

    def _download_sync(self, url: str, output_path: str) -> bool:
        ffmpeg_bin = _FFMPEG_PATH or "ffmpeg"
        try:
            cmd = [
                ffmpeg_bin, "-y",
                "-i", url,
                "-c", "copy",
                "-movflags", "+faststart",
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0 or not Path(output_path).exists():
                if Path(output_path).exists():
                    Path(output_path).unlink(missing_ok=True)
                return False
            validator = CurlCffiFfmpegStrategy(self.download_dir)
            validation = validator._validate_mp4(output_path)
            if not validation.get("valid"):
                logger.warning("Direct download MP4 invalid: %s", validation.get("error"))
                Path(output_path).unlink(missing_ok=True)
                return False
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            if Path(output_path).exists():
                Path(output_path).unlink(missing_ok=True)
            return False

    async def download(self, url: str, output_name: Optional[str] = None) -> Dict[str, Any]:
        safe_name = output_name or url.rstrip("/").split("/")[-1][:80]
        output_path = str(self.download_dir / f"{safe_name}.mp4")

        success = await asyncio.to_thread(self._download_sync, url, output_path)
        if not success:
            return {"error": "direct-ffmpeg: indirme basarisiz"}

        return {
            "success": True,
            "title": safe_name,
            "file_path": output_path,
            "duration": 0,
        }


class YouTubeDownloader:
    """Coklu stratejili VOD indirici.

    Strateji sirasi: curl_cffi+ffmpeg → yt-dlp → direct-ffmpeg
    Herhangi bir stratejiyi devre disi birakabilirsiniz.
    """

    def __init__(self):
        self.download_dir = Path("data/raw_vods")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._strategies: list[DownloadStrategy] = []
        self._enabled: dict[str, bool] = {}
        self._init_strategies()

    def _init_strategies(self):
        all_strategies = [
            CurlCffiFfmpegStrategy(self.download_dir),
            YtDlpStrategy(self.download_dir),
            DirectUrlStrategy(self.download_dir),
        ]
        for s in all_strategies:
            self._enabled[s.name] = s.is_available()
            if s.is_available():
                self._strategies.append(s)

        available = [s.name for s in self._strategies]
        logger.info("Download strategies: %s", ", ".join(available) or "none")

    def set_strategy_enabled(self, name: str, enabled: bool):
        """Belirli bir stratejiyi ac/kapat."""
        for s in self._strategies:
            if s.name == name:
                self._enabled[name] = enabled
                if enabled and s not in self._strategies:
                    self._strategies.insert(0, s)
                elif not enabled and s in self._strategies:
                    self._strategies.remove(s)
                logger.info("Strategy %s: %s", name, "enabled" if enabled else "disabled")
                return

    def get_strategies(self) -> list[Dict[str, Any]]:
        """Mevcut stratejileri listele."""
        return [
            {"name": s.name, "available": s.is_available(), "enabled": self._enabled.get(s.name, False)}
            for s in self._strategies
        ]

    async def download_video(self, url: str, output_name: Optional[str] = None) -> Dict[str, Any]:
        """Sirayla strateji deneyerek videoyu indir.

        Bir strateji basarisiz olursa siradakine gecer.
        Her basarili indirmeyi ffprobe ile dogrular.
        """
        if not self._strategies:
            return {"error": "Hicbir indirme stratejisi mevcut degil"}

        last_error = ""
        for strategy in self._strategies:
            if not self._enabled.get(strategy.name, False):
                continue
            logger.info("Trying download strategy: %s for %s", strategy.name, url)
            result = await strategy.download(url, output_name)
            if result.get("success"):
                file_path = result.get("file_path", "")
                if file_path and Path(file_path).exists():
                    if hasattr(strategy, '_validate_mp4'):
                        validation = strategy._validate_mp4(file_path)
                    else:
                        validator = CurlCffiFfmpegStrategy(self.download_dir)
                        validation = validator._validate_mp4(file_path)
                    if not validation.get("valid"):
                        logger.warning("Downloaded file invalid after %s: %s — cleaning up", strategy.name, validation.get("error"))
                        Path(file_path).unlink(missing_ok=True)
                        last_error = f"validation failed: {validation.get('error')}"
                        continue
                    result["duration"] = validation.get("duration", result.get("duration", 0))
                logger.info("Download success with %s: %s", strategy.name, file_path)
                return result
            last_error = result.get("error", "unknown")
            logger.warning("Strategy %s failed: %s", strategy.name, last_error)

        return {"error": f"Tum stratejiler basarisiz. Son hata: {last_error}"}


youtube_downloader = YouTubeDownloader()
