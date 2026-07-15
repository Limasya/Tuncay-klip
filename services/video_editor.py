"""
Video düzenleme ve post-processing servisi.
- FFmpeg ile klip kesme, yeniden boyutlandırma
- Sosyal medya formatları (portrait/landscape)
- Filigran, renk iyileştirme, geçiş efektleri
- Klip montaj (highlight birleştirme)
"""
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

EXPORTS_DIR = Path("data/exports")
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


class VideoEditor:
    """
    FFmpeg tabanlı otomatik video düzenleme servisi.
    """

    # Çözünürlük profilleri
    RESOLUTIONS = {
        "1080p": {"width": 1920, "height": 1080},
        "720p": {"width": 1280, "height": 720},
        "480p": {"width": 854, "height": 480},
        "portrait": {"width": 1080, "height": 1920},   # TikTok/Reels
        "square": {"width": 1080, "height": 1080},      # Instagram
    }

    async def trim_clip(
        self,
        input_path: str,
        start: float,
        duration: float,
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """Klibi belirli zaman aralığında keser."""
        if not output_path:
            base = Path(input_path).stem
            output_path = str(EXPORTS_DIR / f"{base}_trim.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-ss", str(start),
            "-t", str(duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path, "Klip kesme")

    async def resize_clip(
        self,
        input_path: str,
        resolution: str = "720p",
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """Klibi belirtilen çözünürlüğe yeniden boyutlandırır."""
        res = self.RESOLUTIONS.get(resolution, self.RESOLUTIONS["720p"])

        if not output_path:
            base = Path(input_path).stem
            output_path = str(EXPORTS_DIR / f"{base}_{resolution}.mp4")

        if resolution == "portrait":
            # Portrait: ortadan kırp + pad
            vf = (
                f"crop=ih*9/16:ih,"
                f"scale={res['width']}:{res['height']}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad={res['width']}:{res['height']}:(ow-iw)/2:(oh-ih)/2:black"
            )
        elif resolution == "square":
            vf = (
                f"crop='min(iw,ih)':'min(iw,ih)',"
                f"scale={res['width']}:{res['height']}"
            )
        else:
            vf = (
                f"scale={res['width']}:{res['height']}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad={res['width']}:{res['height']}:(ow-iw)/2:(oh-ih)/2:black"
            )

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", vf,
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            "-crf", "23",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path, f"Boyutlandırma ({resolution})")

    async def add_watermark(
        self,
        input_path: str,
        text: str,
        position: str = "bottom_right",
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """Videoya metin filigranı ekler."""
        if not output_path:
            base = Path(input_path).stem
            output_path = str(EXPORTS_DIR / f"{base}_wm.mp4")

        # Pozisyon
        positions = {
            "top_left": "x=20:y=20",
            "top_right": "x=w-tw-20:y=20",
            "bottom_left": "x=20:y=h-th-20",
            "bottom_right": "x=w-tw-20:y=h-th-20",
            "center": "x=(w-tw)/2:y=(h-th)/2",
        }
        pos = positions.get(position, positions["bottom_right"])

        vf = (
            f"drawtext=text='{text}':"
            f"fontsize=24:fontcolor=white@0.7:"
            f"borderw=2:bordercolor=black@0.5:"
            f"{pos}"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", vf,
            "-c:v", "libx264",
            "-c:a", "copy",
            "-preset", "fast",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path, "Filigran ekleme")

    async def enhance_colors(
        self,
        input_path: str,
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """Renk/kontrast iyileştirme filtresi uygular."""
        if not output_path:
            base = Path(input_path).stem
            output_path = str(EXPORTS_DIR / f"{base}_enhanced.mp4")

        # eq: brightness, contrast, saturation
        vf = "eq=contrast=1.1:saturation=1.2:brightness=0.02"

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", vf,
            "-c:v", "libx264",
            "-c:a", "copy",
            "-preset", "fast",
            "-crf", "22",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path, "Renk iyileştirme")

    async def merge_clips(
        self,
        clip_paths: List[str],
        output_path: Optional[str] = None,
        transition: str = "none",
        transition_duration: float = 0.5,
    ) -> Optional[str]:
        """
        Birden fazla klibi birleştirir.
        Opsiyonel geçiş efekti (fade, dissolve).
        """
        if not output_path:
            output_path = str(EXPORTS_DIR / "merged_highlights.mp4")

        if not clip_paths:
            return None

        if transition == "none" or len(clip_paths) < 2:
            # Basit concat
            return await self._concat_clips(clip_paths, output_path)

        # FFmpeg concat filter ile fade geçişi
        return await self._merge_with_transitions(
            clip_paths, output_path, transition, transition_duration
        )

    async def _concat_clips(
        self,
        clip_paths: List[str],
        output_path: str,
    ) -> Optional[str]:
        """FFmpeg concat demuxer ile klipleri birleştirir."""
        # Liste dosyası oluştur
        list_file = str(EXPORTS_DIR / "concat_list.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for path in clip_paths:
                abs_path = str(Path(path).resolve()).replace("'", "'\\''")
                f.write(f"file '{abs_path}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path, "Klip birleştirme")

    async def _merge_with_transitions(
        self,
        clip_paths: List[str],
        output_path: str,
        transition: str,
        duration: float,
    ) -> Optional[str]:
        """xfade filter ile geçiş efektli birleştirme."""
        if len(clip_paths) < 2:
            return await self._concat_clips(clip_paths, output_path)

        # İlk iki klibi al (basit 2-clip xfade)
        cmd = [
            "ffmpeg", "-y",
            "-i", clip_paths[0],
            "-i", clip_paths[1],
            "-filter_complex",
            (
                f"[0:v][1:v]xfade=transition={transition}:"
                f"duration={duration}:offset=auto[v];"
                f"[0:a][1:a]acrossfade=d={duration}[a]"
            ),
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path, "Geçişli birleştirme")

    async def add_audio_track(
        self,
        video_path: str,
        audio_path: str,
        output_path: Optional[str] = None,
        mix: bool = False,
    ) -> Optional[str]:
        """Videoya ekstra ses track'i ekler veya değiştirir."""
        if not output_path:
            base = Path(video_path).stem
            output_path = str(EXPORTS_DIR / f"{base}_audio.mp4")

        if mix:
            # Mevcut sesle karıştır
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-filter_complex",
                "[0:a][1:a]amix=inputs=2:duration=shortest[a]",
                "-map", "0:v",
                "-map", "[a]",
                "-c:v", "copy",
                "-c:a", "aac",
                output_path,
            ]
        else:
            # Sesi değiştir
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                output_path,
            ]

        return await self._run_ffmpeg(cmd, output_path, "Ses ekleme")

    async def get_video_info(self, video_path: str) -> Dict:
        """Video dosyası bilgilerini döndürür (ffprobe)."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            import json
            data = json.loads(stdout.decode())

            fmt = data.get("format", {})
            streams = data.get("streams", [])
            video_stream = next(
                (s for s in streams if s.get("codec_type") == "video"), {}
            )

            return {
                "duration": float(fmt.get("duration", 0)),
                "size_bytes": int(fmt.get("size", 0)),
                "bitrate": int(fmt.get("bit_rate", 0)),
                "width": int(video_stream.get("width", 0)),
                "height": int(video_stream.get("height", 0)),
                "fps": video_stream.get("r_frame_rate", "0/1"),
                "codec": video_stream.get("codec_name", ""),
            }

        except Exception as e:
            logger.error("Video bilgi alma hatası: %s", e)
            return {}

    async def _run_ffmpeg(
        self,
        cmd: List[str],
        output_path: str,
        operation: str,
    ) -> Optional[str]:
        """FFmpeg komutunu çalıştırır."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

            if proc.returncode == 0:
                logger.info("%s başarılı: %s", operation, output_path)
                return output_path
            else:
                logger.error("%s hatası: %s", operation, stderr.decode()[:500])
                return None

        except asyncio.TimeoutError:
            logger.error("%s zaman aşımı", operation)
            return None
        except Exception as e:
            logger.error("%s hatası: %s", operation, e)
            return None


# Singleton
video_editor = VideoEditor()
