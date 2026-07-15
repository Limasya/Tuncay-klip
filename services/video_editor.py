"""
Video düzenleme ve post-processing servisi.
- FFmpeg ile klip kesme, yeniden boyutlandırma
- Çoklu format desteği: MP4, MOV, MKV, WebM, AVI, WMV
- Sosyal medya aspect ratio'ları: 16:9, 9:16, 1:1, 4:5
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

    # Cozunurluk profilleri (genislik x yukseklik)
    RESOLUTIONS = {
        # Standart cozunurlukler
        "1440p": {"width": 2560, "height": 1440},   # 2K
        "1080p": {"width": 1920, "height": 1080},   # Full HD
        "720p":  {"width": 1280, "height": 720},    # HD
        "480p":  {"width": 854,  "height": 480},    # SD
        "360p":  {"width": 640,  "height": 360},    # SD
        "240p":  {"width": 426,  "height": 240},    # SD
        # Platform bazli boyutlar
        "youtube":          {"width": 1280, "height": 720},    # 16:9 yatay
        "reels":            {"width": 1080, "height": 1920},   # 9:16 dikey
        "tiktok":           {"width": 1080, "height": 1920},   # 9:16 dikey
        "shorts":           {"width": 1080, "height": 1920},   # 9:16 dikey
        "instagram_post":   {"width": 1080, "height": 1080},   # 1:1 kare
        "instagram_vertical": {"width": 1080, "height": 1350}, # 4:5 dikey
        "facebook_post":    {"width": 1080, "height": 1080},   # 1:1 kare
        "facebook_vertical": {"width": 1080, "height": 1350},  # 4:5 dikey
        # Eski uyumluluk
        "portrait": {"width": 1080, "height": 1920},
        "9:16":     {"width": 1080, "height": 1920},
        "square":   {"width": 1080, "height": 1080},
        "1:1":      {"width": 1080, "height": 1080},
        "4:5":      {"width": 1080, "height": 1350},
        "16:9":     {"width": 1920, "height": 1080},
    }

    # Platform boyut profilleri (UI icin)
    PLATFORM_SIZES = {
        "youtube": {
            "label": "YouTube",
            "resolution": "youtube",
            "aspect": "16:9",
        },
        "reels": {
            "label": "Instagram Reels / TikTok / YouTube Shorts",
            "resolution": "reels",
            "aspect": "9:16",
        },
        "instagram_post": {
            "label": "Instagram / Facebook Gonderi (Kare)",
            "resolution": "instagram_post",
            "aspect": "1:1",
        },
        "instagram_vertical": {
            "label": "Instagram / Facebook Gonderi (Dikey)",
            "resolution": "instagram_vertical",
            "aspect": "4:5",
        },
    }

    # Video container formatlari ve FFmpeg codec ayarlari
    FORMAT_PROFILES = {
        "mp4": {
            "extension": "mp4",
            "video_codec": "libx264",
            "audio_codec": "aac",
            "extra_args": ["-movflags", "+faststart"],
            "description": "Evrensel uyumluluk - YouTube, Instagram, TikTok",
        },
        "mov": {
            "extension": "mov",
            "video_codec": "libx264",
            "audio_codec": "aac",
            "extra_args": ["-movflags", "+faststart"],
            "description": "Apple QuickTime - yuksek kalite, edit yazilimlari",
        },
        "mkv": {
            "extension": "mkv",
            "video_codec": "libx264",
            "audio_codec": "aac",
            "extra_args": [],
            "description": "Matroska - coklu ses/altyazi destegi, acik kaynak",
        },
        "webm": {
            "extension": "webm",
            "video_codec": "libvpx-vp9",
            "audio_codec": "libopus",
            "extra_args": ["-b:v", "2M"],
            "description": "Google WebM - HTML5, web optimizasyonu",
        },
        "avi": {
            "extension": "avi",
            "video_codec": "libx264",
            "audio_codec": "mp3",
            "extra_args": [],
            "description": "Microsoft AVI - yuksek kalite, buyuk dosya",
        },
        "wmv": {
            "extension": "wmv",
            "video_codec": "wmv2",
            "audio_codec": "wmav2",
            "extra_args": ["-b:v", "3M"],
            "description": "Windows Media Video - kucuk boyut, online akis",
        },
    }

    def _get_format_profile(self, fmt: str) -> Dict:
        """Format profilini dondurur, varsayilan mp4."""
        return self.FORMAT_PROFILES.get(fmt.lower(), self.FORMAT_PROFILES["mp4"])

    def _build_output_path(
        self, input_path: str, suffix: str, fmt: str = "mp4"
    ) -> str:
        profile = self._get_format_profile(fmt)
        base = Path(input_path).stem
        return str(EXPORTS_DIR / f"{base}_{suffix}.{profile['extension']}")

    async def export_clip(
        self,
        input_path: str,
        resolution: str = "720p",
        output_format: str = "mp4",
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        Klibi belirtilen cozunurluk ve formatta disa aktarir.
        resolution: 1080p, 720p, 480p, portrait, 9:16, square, 1:1, 4:5, 16:9
        output_format: mp4, mov, mkv, webm, avi, wmv
        """
        res = self.RESOLUTIONS.get(resolution, self.RESOLUTIONS["720p"])
        profile = self._get_format_profile(output_format)

        if not output_path:
            output_path = self._build_output_path(
                input_path, f"{resolution}_{output_format}", output_format
            )

        # Aspect ratio'ya gore vf filtresi
        vf = self._build_video_filter(resolution, res)

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", vf,
            "-c:v", profile["video_codec"],
            "-c:a", profile["audio_codec"],
            "-preset", "fast",
            "-crf", "23",
        ]
        cmd.extend(profile["extra_args"])
        cmd.append(output_path)

        return await self._run_ffmpeg(
            cmd, output_path,
            f"Export ({output_format.upper()}, {resolution})"
        )

    def _build_video_filter(self, resolution_key: str, res: Dict) -> str:
        """Resolution key'e gore uygun video filtresini olusturur."""
        w, h = res["width"], res["height"]

        # Dikey (9:16) platformlar
        vertical_9_16 = ("portrait", "9:16", "reels", "tiktok", "shorts")
        # Kare (1:1) platformlar
        square_1_1 = ("square", "1:1", "instagram_post", "facebook_post")
        # Dikey (4:5) platformlar
        vertical_4_5 = ("4:5", "instagram_vertical", "facebook_vertical")

        if resolution_key in vertical_9_16:
            return (
                f"crop=ih*9/16:ih,"
                f"scale={w}:{h}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
            )
        elif resolution_key in square_1_1:
            return (
                f"crop='min(iw,ih)':'min(iw,ih)',"
                f"scale={w}:{h}"
            )
        elif resolution_key in vertical_4_5:
            return (
                f"crop=ih*4/5:ih,"
                f"scale={w}:{h}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
            )
        else:
            # Yatay: 16:9, 1080p, 720p, 480p, 1440p, youtube, vs.
            return (
                f"scale={w}:{h}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
            )

    async def trim_clip(
        self,
        input_path: str,
        start: float,
        duration: float,
        output_path: Optional[str] = None,
        output_format: str = "mp4",
    ) -> Optional[str]:
        """Klibi belirli zaman araliginda keser."""
        profile = self._get_format_profile(output_format)
        if not output_path:
            output_path = self._build_output_path(input_path, "trim", output_format)

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-ss", str(start),
            "-t", str(duration),
            "-c:v", profile["video_codec"],
            "-c:a", profile["audio_codec"],
            "-preset", "fast",
        ]
        cmd.extend(profile["extra_args"])
        cmd.append(output_path)

        return await self._run_ffmpeg(cmd, output_path, "Klip kesme")

    async def resize_clip(
        self,
        input_path: str,
        resolution: str = "720p",
        output_format: str = "mp4",
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """Klibi belirtilen cozunurluge ve formata yeniden boyutlandirir."""
        return await self.export_clip(
            input_path, resolution, output_format, output_path
        )

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
