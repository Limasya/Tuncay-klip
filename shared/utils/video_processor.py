"""
Video Processor — Rust Binary Python Wrapper
─────────────────────────────────────────────
High-performance video operations delegated to the Rust
tuncay-video-processor binary. Drop-in replacement for
asyncio.create_subprocess_exec("ffmpeg", ...) calls.

Usage:
    from shared.utils.video_processor import video_processor

    # Probe video metadata
    info = await video_processor.probe("video.mp4")

    # Extract a clip
    result = await video_processor.clip("vod.mp4", "clip.mp4", start=100.0, duration=30.0)

    # Validate MP4
    valid = await video_processor.validate("clip.mp4")

    # Export for platform
    await video_processor.export("clip.mp4", "tiktok_clip.mp4", platform="tiktok")
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_BINARY_DIR = Path(__file__).resolve().parent.parent.parent / "tools" / "video-processor" / "target" / "release"

if sys.platform == "win32":
    _BINARY = _BINARY_DIR / "tuncay-video-processor.exe"
else:
    _BINARY = _BINARY_DIR / "tuncay-video-processor"


class VideoProcessor:
    """Async wrapper around the Rust video-processor binary."""

    def __init__(self, binary_path: Optional[str | Path] = None):
        self._binary = Path(binary_path) if binary_path else _BINARY

    @property
    def available(self) -> bool:
        return self._binary.exists()

    async def _run(self, args: list[str], timeout: float = 300) -> dict[str, Any]:
        if not self.available:
            raise FileNotFoundError(
                f"Rust binary not found: {self._binary}. "
                "Build with: cd tools/video-processor && cargo build --release"
            )

        cmd = [str(self._binary)] + args
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"success": False, "error": "timeout"}

        stdout_str = stdout.decode(errors="replace") if stdout else ""
        stderr_str = stderr.decode(errors="replace") if stderr else ""

        if proc.returncode != 0:
            try:
                err_data = json.loads(stderr_str)
                return err_data
            except (json.JSONDecodeError, ValueError):
                return {
                    "success": False,
                    "error": stderr_str[:500] or f"Exit code {proc.returncode}",
                }

        try:
            return json.loads(stdout_str)
        except (json.JSONDecodeError, ValueError):
            return {"success": True, "raw_output": stdout_str}

    async def clip(
        self,
        input_path: str,
        output_path: str,
        start: float,
        duration: float,
        vcodec: str = "copy",
        acodec: str = "copy",
        user_agent: Optional[str] = None,
        referer: Optional[str] = None,
        extra_args: Optional[list[str]] = None,
        timeout: float = 600,
    ) -> dict[str, Any]:
        args = [
            "clip",
            "-i", input_path,
            "-o", output_path,
            "-S", str(start),
            "-D", str(duration),
            "--vcodec", vcodec,
            "--acodec", acodec,
        ]
        if user_agent:
            args.extend(["--user-agent", user_agent])
        if referer:
            args.extend(["--referer", referer])
        if extra_args:
            args.extend(["--extra-args"] + extra_args)

        return await self._run(args, timeout=timeout)

    async def probe(self, input_path: str, fmt: str = "json") -> dict[str, Any]:
        args = ["probe", "-i", input_path]
        if fmt != "json":
            args.extend(["--format", fmt])
        return await self._run(args, timeout=30)

    async def validate(
        self,
        input_path: str,
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
    ) -> dict[str, Any]:
        args = ["validate", "-i", input_path]
        if min_duration is not None:
            args.extend(["--min-duration", str(min_duration)])
        if max_duration is not None:
            args.extend(["--max-duration", str(max_duration)])
        return await self._run(args, timeout=30)

    async def export(
        self,
        input_path: str,
        output_path: str,
        platform: str,
        filter: Optional[str] = None,
        timeout: float = 300,
    ) -> dict[str, Any]:
        args = [
            "export",
            "-i", input_path,
            "-o", output_path,
            "-p", platform,
        ]
        if filter:
            args.extend(["--filter", filter])
        return await self._run(args, timeout=timeout)

    async def checksum(self, input_path: str, algorithm: str = "sha256") -> dict[str, Any]:
        args = ["checksum", "-i", input_path, "--algorithm", algorithm]
        return await self._run(args, timeout=60)

    async def batch(
        self,
        manifest_path: str,
        output_dir: str,
        jobs: int = 4,
        timeout: float = 1800,
    ) -> dict[str, Any]:
        args = [
            "batch",
            "-m", manifest_path,
            "-o", output_dir,
            "--jobs", str(jobs),
        ]
        return await self._run(args, timeout=timeout)

    async def is_valid_mp4(self, path: str, timeout: float = 15) -> bool:
        result = await self.validate(path, timeout=timeout)
        return result.get("valid", False)


video_processor = VideoProcessor()
