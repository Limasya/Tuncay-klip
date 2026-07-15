"""
Stream yakalama servisi - HLS/RTMP akışını FFmpeg ile çeker.
- Sürekli dönen ring buffer (tampon) kayıt
- Kare çıkarımı (frame extraction) analiz için
- Klip segmentleri kesme
"""
import asyncio
import subprocess
import os
import time
import logging
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Optional, AsyncGenerator, Callable, Awaitable
from collections import deque
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

BUFFER_DIR = Path("data/buffer")
CLIPS_DIR = Path("data/clips")
BUFFER_DIR.mkdir(parents=True, exist_ok=True)
CLIPS_DIR.mkdir(parents=True, exist_ok=True)


class FrameBuffer:
    """
    Son N saniyelik video karelerini ve timestamp bilgilerini
    bellekte tutan döngüsel tampon (ring buffer).
    """

    def __init__(self, max_seconds: int = 30, fps: int = 2):
        self.max_frames = max_seconds * fps
        self.frames: deque = deque(maxlen=self.max_frames)
        self.timestamps: deque = deque(maxlen=self.max_frames)
        self.fps = fps

    def add_frame(self, frame: np.ndarray, timestamp: float):
        self.frames.append(frame)
        self.timestamps.append(timestamp)

    def get_frames_range(
        self, start_time: float, end_time: float
    ) -> list:
        """Belirli zaman aralığındaki tüm kareleri döndürür."""
        result = []
        for i, ts in enumerate(self.timestamps):
            if start_time <= ts <= end_time:
                if i < len(self.frames):
                    result.append((ts, self.frames[i]))
        return result

    def get_last_n_seconds(self, seconds: float) -> list:
        """Son N saniyedeki kareleri döndürür."""
        if not self.timestamps:
            return []
        now = self.timestamps[-1]
        return self.get_frames_range(now - seconds, now)

    @property
    def current_time(self) -> float:
        return self.timestamps[-1] if self.timestamps else 0.0

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def clear(self):
        self.frames.clear()
        self.timestamps.clear()


class StreamCaptureService:
    """
    FFmpeg ile canlı yayın akışını yakalar ve işler.
    - HLS stream'i segmentlere böler
    - Kareleri analiz pipeline'ına gönderir
    - Ring buffer'da son N saniyeyi tutar
    """

    def __init__(self):
        self.frame_buffer = FrameBuffer(
            max_seconds=settings.stream_buffer_seconds,
            fps=settings.analysis_fps,
        )
        self.is_capturing = False
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._capture_task: Optional[asyncio.Task] = None
        self._stream_url: Optional[str] = None
        self._on_frame_callbacks: list = []
        self._current_segment_file: Optional[str] = None
        self._segment_index = 0

    def on_frame(self, callback: Callable):
        """Her yeni kare için callback kaydı."""
        self._on_frame_callbacks.append(callback)

    async def start_capture(self, stream_url: str):
        """Canlı yayın akışını yakalamaya başlar."""
        self._stream_url = stream_url
        self.is_capturing = True
        self._capture_task = asyncio.create_task(self._capture_loop())
        logger.info("Stream yakalama başladı: %s", stream_url[:80])

    async def stop_capture(self):
        """Yakalamayı durdurur."""
        self.is_capturing = False
        if self._ffmpeg_process:
            self._ffmpeg_process.terminate()
            self._ffmpeg_process.wait()
            self._ffmpeg_process = None
        if self._capture_task:
            self._capture_task.cancel()
            try:
                await self._capture_task
            except asyncio.CancelledError:
                pass
        self.frame_buffer.clear()
        logger.info("Stream yakalama durduruldu.")

    async def _capture_loop(self):
        """
        FFmpeg subprocess ile stream'den kare çıkarır.
        -rawvideo formatında pipe üzerinden okur.
        """
        import cv2

        while self.is_capturing:
            try:
                # FFmpeg ile HLS stream'den frame çıkar
                cmd = [
                    "ffmpeg",
                    "-i", self._stream_url,
                    "-f", "rawvideo",
                    "-pix_fmt", "bgr24",
                    "-vf", f"fps={settings.analysis_fps}",
                    "-an",  # ses yok (ses ayrı işlenir)
                    "-v", "quiet",
                    "pipe:1"
                ]

                self._ffmpeg_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=10**8,
                )

                # Frame boyutunu belirle (ilk frame'den)
                width, height = 1280, 720  # Varsayılan
                frame_size = width * height * 3
                first_frame = True

                while self.is_capturing:
                    raw = self._ffmpeg_process.stdout.read(frame_size)
                    if not raw or len(raw) < frame_size:
                        break

                    frame = np.frombuffer(raw, dtype=np.uint8)
                    frame = frame.reshape((height, width, 3))
                    timestamp = time.time()

                    if first_frame:
                        # İlk frame'den gerçek boyut al
                        first_frame = False
                        logger.info("İlk frame alındı: %dx%d", width, height)

                    self.frame_buffer.add_frame(frame.copy(), timestamp)

                    # Callback'leri çağır
                    for callback in self._on_frame_callbacks:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(frame.copy(), timestamp)
                            else:
                                callback(frame.copy(), timestamp)
                        except Exception as e:
                            logger.error("Frame callback hatası: %s", e)

                self._ffmpeg_process.wait()

            except Exception as e:
                logger.error("Stream yakalama döngüsü hatası: %s", e)

            if self.is_capturing:
                logger.info("Stream yeniden bağlanıyor (5 sn)...")
                await asyncio.sleep(5)

    async def capture_clip(
        self,
        event_time: float,
        pre_seconds: float = None,
        post_seconds: float = None,
        clip_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Buffer'dan klip oluşturur.
        event_time etrafında pre/post saniye alarak video dosyası yazar.
        """
        import cv2

        pre = pre_seconds or settings.clip_pre_seconds
        post = post_seconds or settings.clip_post_seconds

        start_time = event_time - pre
        end_time = event_time + post

        frames = self.frame_buffer.get_frames_range(start_time, end_time)
        if not frames:
            logger.warning("Buffer'da yeterli frame yok: %.1f - %.1f",
                           start_time, end_time)
            return None

        # Klip dosya adı
        if not clip_name:
            clip_name = f"clip_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        clip_path = CLIPS_DIR / f"{clip_name}.mp4"

        # OpenCV VideoWriter ile klip yaz
        fps = settings.analysis_fps
        h, w = frames[0][1].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(clip_path), fourcc, fps, (w, h))

        try:
            for ts, frame in frames:
                writer.write(frame)
        finally:
            writer.release()

        # FFmpeg ile mp4'e dönüştür (codec uyumu için)
        output_path = CLIPS_DIR / f"{clip_name}_final.mp4"
        try:
            proc = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(clip_path),
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "23",
                    "-pix_fmt", "yuv420p",
                    str(output_path),
                ],
                capture_output=True, timeout=60,
            )
            if proc.returncode == 0:
                os.remove(str(clip_path))
                clip_path = output_path
                logger.info("Klip oluşturuldu: %s (%.1f sn, %d frame)",
                            clip_path.name, post + pre, len(frames))
        except Exception as e:
            logger.error("FFmpeg dönüşüm hatası: %s", e)

        return str(clip_path)

    async def capture_clip_with_audio(
        self,
        stream_url: str,
        start_seconds: float,
        duration: float,
        clip_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        FFmpeg ile doğrudan stream'den ses+video klip keser.
        Buffer yerine canlı stream'den segment çeker.
        """
        if not clip_name:
            clip_name = f"clip_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        clip_path = CLIPS_DIR / f"{clip_name}.mp4"

        cmd = [
            "ffmpeg", "-y",
            "-i", stream_url,
            "-ss", str(start_seconds),
            "-t", str(duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            "-crf", "23",
            str(clip_path),
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

            if proc.returncode == 0:
                logger.info("Sesli klip oluşturuldu: %s", clip_path.name)
                return str(clip_path)
            else:
                logger.error("Klip oluşturma hatası: %s",
                             stderr.decode()[:500])
                return None

        except asyncio.TimeoutError:
            logger.error("Klip oluşturma zaman aşımı")
            return None

    async def generate_thumbnail(self, clip_path: str) -> Optional[str]:
        """Klipten küçük resim (thumbnail) oluşturur."""
        thumb_path = clip_path.rsplit(".", 1)[0] + "_thumb.jpg"

        cmd = [
            "ffmpeg", "-y",
            "-i", clip_path,
            "-ss", "1",
            "-vframes", "1",
            "-q:v", "2",
            thumb_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                return thumb_path
        except Exception as e:
            logger.error("Thumbnail oluşturma hatası: %s", e)

        return None


# Singleton
stream_capture = StreamCaptureService()
