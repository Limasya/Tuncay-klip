"""
Akıllı thumbnail üretim motoru.
Yüz algılama, compositing, başlık ekleme, platform optimizasyonu.
"""
import asyncio
import json
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from services.face_tracker import FaceTracker

logger = logging.getLogger(__name__)

THUMBS_DIR = Path("data/thumbnails")
THUMBS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class FaceRegion:
    """Yüz bölge bilgisi."""
    x: int
    y: int
    w: int
    h: int
    confidence: float = 0.0


class ThumbnailEngine:
    """
    Akıllı thumbnail üretim motoru.
    """

    def __init__(self):
        self._face_cascade = None

    async def generate_smart_thumbnail(
        self,
        video_path: str,
        output_path: Optional[str] = None,
        time_point: Optional[float] = None,
        add_title: bool = False,
        title_text: Optional[str] = None,
        title_style: str = "bold",
        platform: str = "tiktok",
        overlay_image: Optional[str] = None,
    ) -> Optional[str]:
        """
        Akıllı thumbnail üretir.

        1. En iyi kareyi seçer (yüz varsa yüz içeren)
        2. Yüz algılama ile optimal kırpma
        3. Başlık overlay
        4. Platform boyut optimizasyonu
        """
        if not output_path:
            base = Path(video_path).stem
            output_path = str(THUMBS_DIR / f"{base}_thumb.jpg")

        # Platform boyutları
        sizes = {
            "tiktok": (1080, 1920),
            "youtube": (1280, 720),
            "youtube_shorts": (1080, 1920),
            "instagram_reels": (1080, 1920),
            "instagram_feed": (1080, 1080),
            "kick": (1280, 720),
        }
        w, h = sizes.get(platform, (1080, 1920))

        # Yüz algılama ile en iyi kareyi seç (yüz koordinatlarıyla birlikte)
        face_x, face_y = 0.5, 0.5  # varsayılan merkez
        if time_point is None:
            time_point, face_x, face_y = await self._find_best_frame(video_path)

        # Thumbnail oluştur
        filters = []

        # 1. Smart Crop + Scale
        if platform in ("tiktok", "youtube_shorts", "instagram_reels"):
            # 9:16 crop, fakat face_x merkezli
            filters.append(
                f"crop=ih*9/16:ih:max(0\\, min(iw-ih*9/16\\, iw*{face_x} - (ih*9/16)/2)):0,"
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
            )
        elif platform == "instagram_feed":
            # 1:1 crop, face_x ve face_y merkezli
            filters.append(
                f"crop='min(iw,ih)':'min(iw,ih)':"
                f"max(0\\, min(iw-min(iw,ih)\\, iw*{face_x} - min(iw,ih)/2)):"
                f"max(0\\, min(ih-min(iw,ih)\\, ih*{face_y} - min(iw,ih)/2)),"
                f"scale={w}:{h}"
            )
        else:
            # 16:9 veya yatay formatlar
            filters.append(
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
            )

        # 2. Renk iyileştirme (thumbnail için daha canlı)
        filters.append("eq=contrast=1.15:saturation=1.25:brightness=0.03")

        # 3. Hafif vignette
        filters.append("vignette=PI/4")

        # 4. Başlık ekle
        if add_title and title_text:
            title_size = 64 if title_style == "bold" else 48
            filters.append(
                f"drawtext=text='{title_text}':"
                f"fontsize={title_size}:"
                f"fontcolor=white:"
                f"borderw=3:bordercolor=black@0.8:"
                f"x=(w-tw)/2:y=h/2-th/2"
            )

        # 5. Overlay image (varsa)
        if overlay_image:
            filters.append(
                f"[1:v]scale=200:200[overlay];"
                f"[0:v][overlay]overlay=W-w-20:20"
            )

        vf = ",".join(f for f in filters if f and f != "null")

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(time_point),
            "-i", video_path,
        ]

        if overlay_image:
            cmd.extend(["-i", overlay_image])

        cmd.extend([
            "-vf", vf,
            "-vframes", "1",
            "-q:v", "2",
            output_path,
        ])

        result = await self._run_ffmpeg(cmd, output_path)

        if result:
            logger.info("Thumbnail üretildi: %s (time=%.1f)", output_path, time_point)

        return result

    async def generate_multi_thumbnail(
        self,
        video_path: str,
        output_dir: Optional[str] = None,
        count: int = 3,
        interval: float = 2.0,
    ) -> List[str]:
        """
        Birden fazla thumbnail üretir (farklı zamanlarda).
        En iyisini seçmek için kullanılır.
        """
        if not output_dir:
            output_dir = str(THUMBS_DIR / Path(video_path).stem)

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Video süresini al
        info = await self._get_video_info(video_path)
        duration = info.get("duration", 10.0)

        # Zaman noktalarını hesapla
        times = []
        for i in range(count):
            t = min(1.0 + i * interval, duration - 0.5)
            times.append(t)

        results = []
        for i, t in enumerate(times):
            out = str(Path(output_dir) / f"thumb_{i:02d}.jpg")
            result = await self.generate_smart_thumbnail(
                video_path, out, time_point=t
            )
            if result:
                results.append(result)

        return results

    async def generate_grid_thumbnail(
        self,
        video_paths: List[str],
        output_path: str,
        cols: int = 2,
        thumb_width: int = 640,
        thumb_height: int = 360,
    ) -> Optional[str]:
        """
        Birden fazla videonun grid'inden thumbnail oluşturur.
        """
        if not video_paths:
            return None

        rows = math.ceil(len(video_paths) / cols)
        total_w = cols * thumb_width
        total_h = rows * thumb_height

        inputs = []
        filter_parts = []

        for i, vp in enumerate(video_paths[:cols * rows]):
            inputs.extend(["-i", vp])
            # Her videoyu thumb boyutuna getir
            filter_parts.append(
                f"[{i}:v]scale={thumb_width}:{thumb_height}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={thumb_width}:{thumb_height}:"
                "(ow-iw)/2:(oh-ih)/2:black,"
                "setsar=1[v{i}]".replace("{i}", str(i))
            )

        # xstack ile birleştir
        input_labels = "".join(f"[v{i}]" for i in range(len(video_paths[:cols * rows])))
        filter_parts.append(
            f"{input_labels}xstack=inputs={len(video_paths[:cols * rows])}:"
            f"layout={_build_grid_layout(cols, thumb_width, thumb_height)}"
        )

        filter_complex = ";".join(filter_parts)

        cmd = [
            "ffmpeg", "-y",
        ] + inputs + [
            "-filter_complex", filter_complex,
            "-vframes", "1",
            "-q:v", "2",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path)

    async def add_text_overlay(
        self,
        image_path: str,
        text: str,
        output_path: str,
        font_size: int = 72,
        font_color: str = "white",
        position: str = "center",
        bg_color: str = "black@0.6",
    ) -> Optional[str]:
        """
        Görüntüye metin overlay ekler.
        """
        positions = {
            "center": "x=(w-tw)/2:y=(h-th)/2",
            "top": "x=(w-tw)/2:y=50",
            "bottom": "x=(w-tw)/2:y=h-th-50",
            "top_left": "x=50:y=50",
            "top_right": "x=w-tw-50:y=50",
            "bottom_left": "x=50:y=h-th-50",
            "bottom_right": "x=w-tw-50:y=h-th-50",
        }
        pos = positions.get(position, positions["center"])

        # Background box
        vf = (
            f"drawbox=x=0:y=(h-th)/2-20:"
            f"w=iw:h=th+40:color={bg_color}:t=fill,"
            f"drawtext=text='{text}':"
            f"fontsize={font_size}:"
            f"fontcolor={font_color}:"
            f"{pos}"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", image_path,
            "-vf", vf,
            "-vframes", "1",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path)

    async def _find_best_frame(self, video_path: str) -> Tuple[float, float, float]:
        """
        En iyi kare zamanını bulur ve (time, face_x, face_y) döndürür.
        OpenCV & MediaPipe ile Saliency/Yüz analizi yapar.
        """
        info = await self._get_video_info(video_path)
        duration = float(info.get("duration", 10.0))
        default_time = duration * 0.5
        
        try:
            tracker = FaceTracker()
            trajectory = await tracker.get_face_trajectory(video_path, fps=2)
            
            if "error" not in trajectory and isinstance(trajectory, list) and len(trajectory) > 0:
                # En büyük yüze (size) sahip olan frame'i bul (en net yüz)
                best_frame = max(trajectory, key=lambda x: x.get("size", 0.0))
                
                time_point = float(best_frame.get("time", default_time))
                face_x = float(best_frame.get("x", 0.5))
                face_y = float(best_frame.get("y", 0.5))
                
                logger.info(f"Smart Thumbnail seçildi -> Zaman: {time_point}s, Yüz X: {face_x}")
                return time_point, face_x, face_y
                
        except Exception as e:
            logger.warning(f"FaceTracker hatası, varsayılan kareye düşülüyor: {e}")

        # Eğer yüz bulunamazsa veya hata olursa videonun %50'sini ve ortasını dön
        return default_time, 0.5, 0.5

    async def _get_video_info(self, path: str) -> Dict:
        """Video dosyası bilgilerini alır."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            data = json.loads(stdout.decode())
            return {
                "duration": float(data.get("format", {}).get("duration", 10)),
            }
        except Exception:
            return {"duration": 10.0}

    async def _run_ffmpeg(
        self, cmd: List[str], output_path: str
    ) -> Optional[str]:
        """FFmpeg komutunu çalıştırır."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

            if proc.returncode == 0:
                return output_path
            else:
                logger.error("Thumbnail FFmpeg hatası: %s", stderr.decode()[:300])
                return None
        except Exception as e:
            logger.error("Thumbnail hatası: %s", e)
            return None


def _build_grid_layout(cols: int, w: int, h: int) -> str:
    """Grid layout string'i üretir."""
    positions = []
    for row in range(10):  # max 10 satır
        for col in range(cols):
            x = col * w
            y = row * h
            positions.append(f"{x}|{y}")
    return "+".join(positions)


# Singleton
thumbnail_engine = ThumbnailEngine()
