"""
FFmpeg/FFprobe yardimcisi
─────────────────────────
9+ serviste tekrar eden FFmpeg/FFprobe subprocess pattern'ini birlestirir.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class FFmpegRunner:
    """FFmpeg ve FFprobe icin birlesik subprocess arayuzu.

    Ornegin:
        runner = FFmpegRunner()
        info = await runner.probe("video.mp4")
        success = await runner.run([
            "ffmpeg", "-y", "-i", "input.mp4", "-c:v", "libx264", "output.mp4"
        ], timeout=120)
    """

    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"):
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe

    async def run(
        self,
        cmd: list[str],
        timeout: float = 300,
        capture_stderr: bool = True,
    ) -> dict[str, Any]:
        """FFmpeg komutu calistir.

        Returns:
            {"success": bool, "returncode": int, "stdout": str, "stderr": str}
        """
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE if capture_stderr else asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"success": False, "returncode": -1, "stdout": "", "stderr": "timeout"}

        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace") if stdout else "",
            "stderr": stderr.decode(errors="replace") if stderr else "",
        }

    async def probe(
        self,
        input_path: str,
        timeout: float = 30,
    ) -> Optional[dict[str, Any]]:
        """ffprobe ile medya bilgisi cek (JSON formatinda).

        Returns:
            ffprobe JSON output veya None (hata durumunda).
        """
        cmd = [
            self._ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            input_path,
        ]
        result = await self.run(cmd, timeout=timeout, capture_stderr=True)
        if not result["success"]:
            logger.warning("ffprobe basarisiz: %s", result["stderr"][:200])
            return None
        try:
            return json.loads(result["stdout"])
        except json.JSONDecodeError:
            logger.warning("ffprobe JSON parse hatasi: %s", result["stdout"][:200])
            return None

    async def is_valid_mp4(self, path: str, timeout: float = 15) -> bool:
        """MP4 dosyasinin gecerli olup olmadigini kontrol et."""
        info = await self.probe(path, timeout=timeout)
        if not info:
            return False
        fmt = info.get("format", {})
        format_name = fmt.get("format_name", "")
        duration = float(fmt.get("duration", 0))
        return "mp4" in format_name.lower() and duration > 0


# Modul seviyesinde singleton
ffmpeg_runner = FFmpegRunner()
