"""
Live Stream Processor — Gerçek zamanlı HLS akışı işleyici
========================================================
Canlı yayını diske hiç yazmadan, pipe üzerinden Ham ses/video olarak alır,
C++ ring buffer'a (ses) ve Python deque'ye (video) yazar.

Mimari:
  Kick HLS (.m3u8)
       │
       ▼
  ┌─ FFmpeg (audio) ──► stdout PCM f32le ──► C++ RingBuffer<float> ──┐
  │                                                                   │
  └─ FFmpeg (video) ──► stdout rawvideo ──► Python deque (frames) ───┘
       │                                                          │
       │    ┌────────────────────────────────────────────────────┘
       │    │
       │    ├── AnalysisPipeline.process_frame(frame, ts)
       │    │     ├── FaceEmotionAnalyzer.analyze_frame(frame)
       │    │     ├── MotionAnalyzer.analyze_frame(frame)
       │    │     └── AudioAnalyzer.get_current_analysis()
       │    │
       │    └── EventDetector → composite score → hysteresis
       │
       └── audio_analyzer._process_chunk(samples)  →  spike detection
                                                        │
                                              EventBus → microservices
                                              (EventDetectorService + DecisionEngineService)
                                                        │
                                              CLIP_CANDIDATE → klip üretimi

Diskte oluşan tek şey: nihai klip dosyaları.
"""
from __future__ import annotations

import asyncio
import logging
import struct
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

import numpy as np

logger = logging.getLogger("live_stream_processor")


# ── Video Frame Buffer (Python deque) ────────────────────────────────────────

@dataclass
class VideoFrame:
    """Tek bir video karesi + zaman damgası."""
    timestamp: float        # stream başlangıcından itibaren saniye
    frame: np.ndarray       # RGB24 numpy array (downscaled)
    width: int
    height: int
    frame_index: int


class VideoFrameBuffer:
    """
    Son N saniyelik video karelerini bellekte tutan döngüsel tampon.
    C++ ring buffer'ın video karşılığı — numpy array'ler içindeque tabanlı.

    Adaptive FPS:
      Stream state'e göre FPS dinamik olarak değiştirilir:
        STEADY → 2fps  (normal akış)
        HIGH_ENERGY → 5fps (yoğun an)
        PEAK_MOMENT → 10fps (zirve an)
    """

    # Stream state → FPS mapping
    STATE_FPS_MAP = {
        "steady": 2,
        "high_energy": 5,
        "peak_moment": 10,
        "warming_up": 2,
        "cooling_down": 2,
        "starting": 2,
        "ending": 2,
    }

    def __init__(self, max_seconds: int = 180, target_fps: int = 2):
        self._max_seconds = max_seconds
        self._current_fps = target_fps
        self.max_frames = max_seconds * target_fps
        self.frames: deque[VideoFrame] = deque(maxlen=self.max_frames)
        self.target_fps = target_fps
        self._frame_interval = 1.0 / target_fps
        self._last_added_time: float = float("-inf")
        self.total_frames_received: int = 0
        self.total_frames_dropped: int = 0

    def set_fps(self, new_fps: int):
        """FPS'i dinamik olarak değiştir."""
        if new_fps == self._current_fps:
            return
        if new_fps < 1 or new_fps > 30:
            return

        old_fps = self._current_fps
        self._current_fps = new_fps
        self.target_fps = new_fps
        self._frame_interval = 1.0 / new_fps
        self.max_frames = self._max_seconds * new_fps

        # Deque maxlen'i güncelle (yeni eklenen karelerden itibaren geçerli)
        self.frames = deque(self.frames, maxlen=self.max_frames)

        logger.info("Video FPS değiştirildi: %d → %d (max_frames=%d)",
                     old_fps, new_fps, self.max_frames)

    def update_from_state(self, stream_state: str):
        """Stream state'e göre FPS'i güncelle."""
        new_fps = self.STATE_FPS_MAP.get(stream_state.lower(), self.target_fps)
        self.set_fps(new_fps)

    def maybe_add(self, frame: np.ndarray, timestamp: float,
                  width: int, height: int) -> bool:
        """FPS düşürerek kare ekle. True = eklendi, False = atlandı."""
        self.total_frames_received += 1
        elapsed = timestamp - self._last_added_time
        if elapsed < self._frame_interval - 1e-9:
            self.total_frames_dropped += 1
            return False

        vf = VideoFrame(
            timestamp=timestamp,
            frame=frame,
            width=width,
            height=height,
            frame_index=self.total_frames_received,
        )
        self.frames.append(vf)
        self._last_added_time = timestamp
        return True

    def get_range(self, start_time: float, end_time: float) -> List[VideoFrame]:
        """Belirli zaman aralığındaki kareleri döndür."""
        return [f for f in self.frames if start_time <= f.timestamp <= end_time]

    def get_last_n_seconds(self, seconds: float) -> List[VideoFrame]:
        if not self.frames:
            return []
        now = self.frames[-1].timestamp
        return self.get_range(now - seconds, now)

    @property
    def current_time(self) -> float:
        return self.frames[-1].timestamp if self.frames else 0.0

    @property
    def count(self) -> int:
        return len(self.frames)

    @property
    def current_fps(self) -> int:
        return self._current_fps

    def clear(self):
        self.frames.clear()
        self._last_added_time = 0.0


# ── Signal Scores (per-second fusion output) ─────────────────────────────────

@dataclass
class SignalScore:
    """Tek bir saniyedeki füzyon skoru — tüm motorlardan gelen sinyaller."""
    timestamp: float
    audio_energy: float = 0.0
    audio_peak: float = 0.0
    audio_bpm: float = 0.0
    video_motion: float = 0.0
    video_scene_change: float = 0.0
    emotion_intensity: float = 0.0
    chat_velocity: float = 0.0
    composite_score: float = 0.0


class SignalScoreBuffer:
    """
    Zaman serisi skorları — son N dakikalık skor geçmişi.
    Decision engine bu tampondan okur.
    """

    def __init__(self, max_seconds: int = 300):
        self.max_entries = max_seconds  # 1 entry = 1 saniye
        self.scores: deque[SignalScore] = deque(maxlen=self.max_entries)

    def append(self, score: SignalScore):
        self.scores.append(score)

    def get_range(self, start_time: float, end_time: float) -> List[SignalScore]:
        return [s for s in self.scores if start_time <= s.timestamp <= end_time]

    def get_last_n(self, n: int) -> List[SignalScore]:
        return list(self.scores)[-n:] if self.scores else []

    @property
    def latest(self) -> Optional[SignalScore]:
        return self.scores[-1] if self.scores else None


# ── FFmpeg Pipe Manager ──────────────────────────────────────────────────────

class FfmpegPipeManager:
    """
    FFmpeg'i iki bağımsız subprocess olarak başlatır:
    1. Audio pipe: HLS → PCM f32le mono 44100Hz → stdout
    2. Video pipe: HLS → rawvideo rgb24 320x240 → stdout

    Hiçbir dosyaya yazmaz, tüm veri pipe üzerinden gelir.

    Reconnection:
      Pipe reader boş data veya hata aldığında otomatik reconnect dener.
      Exponential backoff: 2s → 4s → 8s → ... → 60s (cap)
      Max 10 deneme sonrası _on_disconnect callback çağrılır.
    """

    def __init__(self):
        self._audio_process: Optional[subprocess.Popen] = None
        self._video_process: Optional[subprocess.Popen] = None
        self._running = False
        self._stream_url: Optional[str] = None
        self._audio_cb = None
        self._video_cb = None

        # Reconnection state
        self._reconnect_count = 0
        self._max_reconnect_attempts = 10
        self._reconnect_base_delay = 2.0
        self._reconnect_max_delay = 60.0
        self._on_disconnect_callback: Optional[Callable] = None
        self._on_reconnect_callback: Optional[Callable] = None

        # Pipe reader tasks (kept for cleanup)
        self._reader_tasks: list = []

    def on_disconnect(self, callback: Callable):
        """Bağlantı koptuğunda çağrılacak callback."""
        self._on_disconnect_callback = callback

    def on_reconnect(self, callback: Callable):
        """Yeniden bağlandığında çağrılacak callback."""
        self._on_reconnect_callback = callback

    async def start(self, stream_url: str,
                    audio_cb: Callable[[bytes], Coroutine] | None = None,
                    video_cb: Callable[[bytes, int, int], Coroutine] | None = None):
        """Her iki pipe'ı başlat."""
        self._stream_url = stream_url
        self._audio_cb = audio_cb
        self._video_cb = video_cb
        self._running = True
        self._reconnect_count = 0

        await self._spawn_ffmpeg_processes()

        tasks = self._start_readers()
        return tasks

    async def _spawn_ffmpeg_processes(self):
        """FFmpeg subprocess'lerini başlat."""
        if self._audio_process:
            await self._kill_process(self._audio_process)
        if self._video_process:
            await self._kill_process(self._video_process)

        audio_cmd = [
            "ffmpeg",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", self._stream_url,
            "-vn",
            "-ac", "1",
            "-ar", "44100",
            "-f", "f32le",
            "-acodec", "pcm_f32le",
            "-v", "quiet",
            "pipe:1",
        ]

        video_cmd = [
            "ffmpeg",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", self._stream_url,
            "-an",
            "-vf", "scale=320:240",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-v", "quiet",
            "pipe:1",
        ]

        logger.info("FFmpeg pipes başlatılıyor...")

        self._audio_process = subprocess.Popen(
            audio_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=10**7,
        )

        self._video_process = subprocess.Popen(
            video_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=10**7,
        )

    def _start_readers(self) -> list:
        """Okuma task'larını başlat."""
        tasks = []
        if self._audio_cb:
            tasks.append(asyncio.create_task(
                self._read_audio_pipe(self._audio_process, self._audio_cb)
            ))
        if self._video_cb:
            tasks.append(asyncio.create_task(
                self._read_video_pipe(self._video_process, self._video_cb)
            ))
        self._reader_tasks = tasks
        return tasks

    async def _read_audio_pipe(self, proc: subprocess.Popen,
                                callback: Callable[[bytes], Coroutine]):
        """Audio pipe'tan PCM chunk'ları oku + reconnect."""
        CHUNK_BYTES = 44100 * 4  # 1 saniyelik chunk (float32 = 4 byte)
        logger.info("Audio pipe okuma başladı (chunk=%d bytes = 1s)", CHUNK_BYTES)

        loop = asyncio.get_event_loop()
        while self._running:
            try:
                data = await loop.run_in_executor(
                    None, proc.stdout.read, CHUNK_BYTES
                )
                if not data:
                    logger.warning("Audio pipe kapandı")
                    await self._attempt_reconnect("audio")
                    return
                await callback(data)
            except Exception as e:
                logger.error("Audio pipe okuma hatası: %s", e)
                await self._attempt_reconnect("audio")
                return

    async def _read_video_pipe(self, proc: subprocess.Popen,
                                callback: Callable[[bytes, int, int], Coroutine]):
        """Video pipe'tan raw frame chunk'ları oku + reconnect."""
        FRAME_SIZE = 320 * 240 * 3  # rgb24 = 3 byte/pixel
        logger.info("Video pipe okuma başladı (frame=%d bytes)", FRAME_SIZE)

        loop = asyncio.get_event_loop()
        while self._running:
            try:
                data = await loop.run_in_executor(
                    None, proc.stdout.read, FRAME_SIZE
                )
                if not data or len(data) < FRAME_SIZE:
                    logger.warning("Video pipe kapandı veya eksik veri")
                    await self._attempt_reconnect("video")
                    return
                await callback(data, 320, 240)
            except Exception as e:
                logger.error("Video pipe okuma hatası: %s", e)
                await self._attempt_reconnect("video")
                return

    async def _attempt_reconnect(self, source: str):
        """Exponential backoff ile yeniden bağlantı dene."""
        if not self._running:
            return

        self._reconnect_count += 1
        if self._reconnect_count > self._max_reconnect_attempts:
            logger.error(
                "FFmpeg reconnect başarısız: %d deneme aşıldı, bağlantı kesiliyor",
                self._max_reconnect_attempts,
            )
            if self._on_disconnect_callback:
                try:
                    await self._on_disconnect_callback()
                except Exception:
                    pass
            self._running = False
            return

        delay = min(
            self._reconnect_base_delay * (2 ** (self._reconnect_count - 1)),
            self._reconnect_max_delay,
        )

        logger.warning(
            "FFmpeg reconnect denemesi %d/%d (%s source), bekleme: %.1fs",
            self._reconnect_count,
            self._max_reconnect_attempts,
            source,
            delay,
        )

        await asyncio.sleep(delay)

        if not self._running:
            return

        try:
            await self._spawn_ffmpeg_processes()
            self._start_readers()
            self._reconnect_count = 0
            logger.info("FFmpeg pipes yeniden başlatıldı")

            if self._on_reconnect_callback:
                try:
                    await self._on_reconnect_callback(self._reconnect_count)
                except Exception:
                    pass
        except Exception as e:
            logger.error("FFmpeg yeniden başlatma hatası: %s", e)

    async def _kill_process(self, proc: subprocess.Popen):
        """Process'i temizle."""
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    async def stop(self):
        """Her iki pipe'ı durdur."""
        self._running = False
        for proc in [self._audio_process, self._video_process]:
            if proc:
                await self._kill_process(proc)
        self._audio_process = None
        self._video_process = None
        logger.info("FFmpeg pipes durduruldu.")


# ── Live Stream Processor ────────────────────────────────────────────────────

class LiveStreamProcessor:
    """
    Canlı HLS akışını diske hiç yazmadan işler.

    Akış:
      HLS → FFmpeg pipes → RAM (ring buffer + deque) → analiz motorları → decision engine

    Diskte oluşan tek şey: nihai klip dosyaları.
    """

    def __init__(
        self,
        audio_buffer_seconds: int = 180,     # Son 3 dakika ses
        video_buffer_seconds: int = 180,      # Son 3 dakika video
        video_fps: int = 2,                   # Analiz için kare hızı
        audio_sample_rate: float = 44100.0,
        stream_id: str = "default",
    ):
        self.audio_sample_rate = audio_sample_rate
        self._stream_id = stream_id
        self._ffmpeg = FfmpegPipeManager()
        self._running = False
        self._start_time: float = 0.0

        # ── Buffers ────────────────────────────────────────────────────────
        # C++ ring buffer (audio) — signal_engine üzerinden
        self._audio_ring = None  # signal_engine RingBuffer instance
        self._audio_buffer_seconds = audio_buffer_seconds

        # Python deque (video frames)
        self._video_buffer = VideoFrameBuffer(
            max_seconds=video_buffer_seconds,
            target_fps=video_fps,
        )

        # Fusion scores (per-second)
        self._score_buffer = SignalScoreBuffer(max_seconds=300)

        # ── Streaming Analysis Engines ─────────────────────────────────────
        self._pipeline = None   # AnalysisPipeline (lazy init)
        self._streaming_audio = None  # streaming AudioAnalyzer (lazy init)
        self._chat_producer = None  # ChatSignalProducer (lazy init)

        # ── Callbacks ──────────────────────────────────────────────────────
        self._on_audio_callbacks: list = []
        self._on_video_callbacks: list = []
        self._on_score_callbacks: list = []
        self._on_clip_callbacks: list = []  # CLIP_CANDIDATE callbacks
        self._analysis_tasks: list = []

        # ── Per-second analysis accumulator ────────────────────────────────
        self._audio_chunk_buffer: list = []  # 1 saniyelik ses chunk'ları
        self._audio_chunk_target_bytes = int(audio_sample_rate * 4)  # 1s = 44100*4 bytes

    async def start(self, stream_url: str):
        """Canlı yayın işlemeyi başlat."""
        self._running = True
        self._start_time = time.time()

        # Streaming analiz motorlarını başlat
        try:
            from services.analysis.pipeline import analysis_pipeline
            from services.analysis.audio_analysis import audio_analyzer as stream_audio
            self._pipeline = analysis_pipeline
            self._streaming_audio = stream_audio
            await self._pipeline.start()
            logger.info("AnalysisPipeline başlatıldı (emotion+motion+audio)")
        except Exception as e:
            logger.warning("AnalysisPipeline başlatılamadı: %s", e)

        # Chat signal producer'ı başlat
        try:
            from services.chat_signal_producer import chat_signal_producer
            self._chat_producer = chat_signal_producer
            await self._chat_producer.start(stream_id=self._stream_id)
            logger.info("Chat signal producer başlatıldı")
        except Exception as e:
            logger.warning("Chat signal producer başlatılamadı: %s", e)

        # C++ ring buffer'ı başlat
        try:
            from signal_engine.python.signal_client import signal_engine as se
            if se.available:
                import math
                capacity = 2 ** math.ceil(math.log2(
                    self._audio_buffer_seconds * int(self.audio_sample_rate)
                ))
                self._audio_ring = se.create_ring_buffer(capacity)
                logger.info("C++ ring buffer oluşturuldu: kapasite=%d (~%.0fs)",
                            capacity, capacity / self.audio_sample_rate)
            else:
                logger.warning("signal_engine mevcut değil, ses buffer Python'da tutulacak")
        except Exception as e:
            logger.warning("C++ ring buffer oluşturulamadı: %s", e)

        # Stream state listener — adaptive FPS için
        self._analysis_tasks.append(
            asyncio.create_task(self._state_watcher_loop())
        )

        # FFmpeg pipe'larını başlat
        tasks = await self._ffmpeg.start(
            stream_url,
            audio_cb=self._on_audio_chunk,
            video_cb=self._on_video_frame,
        )

        # Analiz task'larını başlat
        self._analysis_tasks = [
            asyncio.create_task(self._audio_analysis_loop()),
            asyncio.create_task(self._video_analysis_loop()),
            asyncio.create_task(self._fusion_loop()),
        ]

        all_tasks = tasks + self._analysis_tasks
        logger.info("Live stream processor başlatıldı: %s", stream_url[:80])
        return all_tasks

    async def stop(self):
        """İşlemeyi durdur."""
        self._running = False
        await self._ffmpeg.stop()
        if self._pipeline:
            await self._pipeline.stop()
        if self._chat_producer:
            await self._chat_producer.stop()
        for t in self._analysis_tasks:
            t.cancel()
        if self._audio_ring:
            self._audio_ring = None
        self._video_buffer.clear()
        logger.info("Live stream processor durduruldu.")

    # ── Audio pipe callback ──────────────────────────────────────────────────

    async def _on_audio_chunk(self, data: bytes):
        """FFmpeg audio pipe'tan gelen PCM chunk'ını buffer'a it."""
        import numpy as np

        # C++ ring buffer'a it (high-performance FFT/beats için)
        if self._audio_ring:
            n_samples = len(data) // 4  # float32 = 4 byte
            samples = struct.unpack(f"<{n_samples}f", data[:n_samples * 4])
            self._audio_ring.push(list(samples))

        # Streaming audio analyzer'a besle (spike detection için)
        if self._streaming_audio:
            try:
                n_samples = len(data) // 4
                samples = np.frombuffer(data[:n_samples * 4], dtype=np.float32)
                self._streaming_audio._process_chunk(samples)

                # Spike tespit edildiyse EventBus'a yayınla
                analysis = self._streaming_audio.get_current_analysis()
                if analysis.get("is_spike"):
                    # EventBus'a audio.spike event'i yayınla
                    try:
                        from shared.event_bus import EventBus, EventType
                        bus = EventBus()
                        await bus.publish_quick(
                            EventType.AUDIO_SPIKE,
                            {
                                "rms_energy": analysis["rms_energy"],
                                "baseline_energy": analysis["baseline_energy"],
                                "spike_ratio": analysis["spike_ratio"],
                                "speech_detected": analysis.get("speech_detected", False),
                            },
                            source_service="live-stream-processor",
                            stream_id=self._stream_id,
                        )
                    except ImportError:
                        pass
                    except Exception as e:
                        logger.debug("Audio spike event publish hatası: %s", e)

                    for cb in self._on_score_callbacks:
                        try:
                            score = SignalScore(
                                timestamp=self.current_time,
                                audio_energy=analysis["rms_energy"],
                                audio_peak=analysis["spike_ratio"],
                            )
                            await cb(score)
                        except Exception as e:
                            logger.error("Audio spike callback hatası: %s", e)
            except Exception as e:
                logger.debug("Streaming audio analiz hatası: %s", e)

        # 1 saniyelik chunk tamamlandığında analiz tetikle
        self._audio_chunk_buffer.append(data)
        current_bytes = sum(len(c) for c in self._audio_chunk_buffer)
        if current_bytes >= self._audio_chunk_target_bytes:
            combined = b"".join(self._audio_chunk_buffer)
            self._audio_chunk_buffer.clear()

            for cb in self._on_audio_callbacks:
                try:
                    await cb(combined, self.current_time)
                except Exception as e:
                    logger.error("Audio callback hatası: %s", e)

    # ── Video pipe callback ──────────────────────────────────────────────────

    async def _on_video_frame(self, data: bytes, width: int, height: int):
        """FFmpeg video pipe'tan gelen frame'i buffer'a it + analiz motorlarına besle."""
        frame = np.frombuffer(data[:width * height * 3], dtype=np.uint8)
        frame = frame.reshape((height, width, 3))
        timestamp = self.current_time

        added = self._video_buffer.maybe_add(frame, timestamp, width, height)
        if added:
            # AnalysisPipeline'a besle (emotion+motion+audio birleşik analiz)
            if self._pipeline and self._pipeline.is_running:
                try:
                    result = await self._pipeline.process_frame(frame, timestamp)
                    if result and result.get("triggered"):
                        logger.info(
                            "TRIGGER from pipeline: score=%.2f, type=%s",
                            result["composite_score"],
                            result.get("trigger_type"),
                        )
                        # EventBus'a publish et — EventDetectorService alacak
                        await self._publish_analysis_events(result, timestamp)
                        for cb in self._on_clip_callbacks:
                            try:
                                await cb(result)
                            except Exception as e:
                                logger.error("Clip trigger callback hatası: %s", e)
                except Exception as e:
                    logger.debug("Pipeline frame analiz hatası: %s", e)

            for cb in self._on_video_callbacks:
                try:
                    await cb(frame, timestamp, width, height)
                except Exception as e:
                    logger.error("Video callback hatası: %s", e)

    async def _publish_analysis_events(self, pipeline_result: Dict, timestamp: float):
        """Pipeline sonuçlarını EventBus'a event olarak yayınla.
        EventDetectorService bu event'leri alıp scoring'a ekler."""
        try:
            from shared.event_bus import EventBus, EventType, SystemEvent
            bus = EventBus()

            # Emotion event
            emotion = pipeline_result.get("emotion", {})
            if emotion.get("face_detected"):
                await bus.publish_quick(
                    EventType.EMOTION_DETECTED,
                    {
                        "dominant_emotion": emotion.get("dominant_emotion", "neutral"),
                        "confidence": emotion.get("emotion_confidence", 0.0),
                        "is_exciting": emotion.get("is_exciting", False),
                        "faces": emotion.get("face_count", 0),
                    },
                    source_service="live-stream-processor",
                    stream_id=self._stream_id,
                )

            # Motion/pose event
            motion = pipeline_result.get("motion", {})
            if motion.get("is_significant_event"):
                await bus.publish_quick(
                    EventType.POSE_DETECTED,
                    {
                        "gesture": motion.get("event_type", "none"),
                        "motion_score": motion.get("motion_score", 0.0),
                        "significant": True,
                    },
                    source_service="live-stream-processor",
                    stream_id=self._stream_id,
                )

            # Scene change (composite score很高时)
            if pipeline_result.get("composite_score", 0) > 0.7:
                await bus.publish_quick(
                    EventType.SCENE_CHANGE,
                    {
                        "composite_score": pipeline_result["composite_score"],
                        "trigger_type": pipeline_result.get("trigger_type", "composite"),
                    },
                    source_service="live-stream-processor",
                    stream_id=self._stream_id,
                )

        except ImportError:
            logger.debug("EventBus mevcut değil, eventler publish edilemedi")
        except Exception as e:
            logger.debug("Event publish hatası: %s", e)

    # ── Analysis loops ───────────────────────────────────────────────────────

    async def _audio_analysis_loop(self):
        """Sürekli ses analizi — ring buffer'dan son N saniyeyi oku, features çıkar."""
        try:
            from signal_engine.python.signal_client import signal_engine as se
            if not se.available:
                logger.warning("signal_engine mevcut değil, audio analysis atlandı")
                return
        except ImportError:
            return

        ANALYSIS_WINDOW = 5  # 5 saniyelik pencere
        STEP = 1             # Her saniye analiz et
        samples_per_second = int(self.audio_sample_rate)

        while self._running:
            await asyncio.sleep(STEP)
            if not self._audio_ring or self._audio_ring.size < samples_per_second:
                continue

            try:
                # Ring buffer'dan son N saniye ses örneği oku
                n_samples = ANALYSIS_WINDOW * samples_per_second
                samples = self._audio_ring.pop(min(n_samples, self._audio_ring.size))

                if len(samples) < 1024:
                    continue

                # C++ engine ile analiz (asyncio thread'de)
                result = await asyncio.to_thread(
                    se.analyze_audio, samples, self.audio_sample_rate
                )

                if isinstance(result, dict) and result.get("success"):
                    # Skoru score buffer'a yaz
                    score = SignalScore(
                        timestamp=self.current_time,
                        audio_energy=result.get("total_energy", 0),
                        audio_peak=result.get("peak_amplitude", 0),
                        audio_bpm=result.get("beats", [{}])[0].get("bpm", 0)
                        if result.get("beats") else 0,
                    )
                    self._score_buffer.append(score)

                    for cb in self._on_score_callbacks:
                        try:
                            await cb(score)
                        except Exception as e:
                            logger.error("Score callback hatası: %s", e)

            except Exception as e:
                logger.debug("Audio analysis hatası: %s", e)

    async def _video_analysis_loop(self):
        """Sürekli video analizi — AnalysisPipeline sonuçlarını score buffer'a yazar.
        Her 2 saniyede bir pipeline'daki son durumu okur."""
        STEP = 2

        while self._running:
            await asyncio.sleep(STEP)
            if not self._pipeline:
                continue

            try:
                # Pipeline'ın kendi istatistiklerinden bilgi al
                stats = self._pipeline.stats
                if stats.get("processed_frames", 0) == 0:
                    continue

                # Son tetikleme bilgisini score buffer'a yaz
                if stats.get("events_triggered", 0) > 0:
                    score = SignalScore(
                        timestamp=self.current_time,
                        video_motion=0.8,  # Pipeline tetiklediyse yüksek motion varsay
                    )
                    self._score_buffer.append(score)

            except Exception as e:
                logger.debug("Video analysis loop hatası: %s", e)

    async def _fusion_loop(self):
        """Tüm sinyalleri birleştir, hysteresis ile tetikleme."""
        STEP = 1
        THRESHOLD = 0.6
        COOLDOWN = 30  # saniye

        last_trigger = 0.0
        consecutive_high = 0
        REQUIRED_CONSECUTIVE = 3  # 3 saniye üst üste yüksek skor

        while self._running:
            await asyncio.sleep(STEP)

            score = self._score_buffer.latest
            if not score:
                continue

            composite = (
                min(1.0, score.audio_energy / 10000) * 0.3 +
                score.video_motion * 0.2 +
                score.emotion_intensity * 0.2 +
                min(1.0, score.chat_velocity / 50) * 0.15 +
                (1.0 if score.audio_bpm > 120 else 0.0) * 0.15
            )
            score.composite_score = composite

            if composite >= THRESHOLD:
                consecutive_high += 1
            else:
                consecutive_high = 0

            if (consecutive_high >= REQUIRED_CONSECUTIVE and
                    time.time() - last_trigger > COOLDOWN):
                logger.info(
                    "KLIP TETIKLEME! score=%.2f, audio=%.1f, motion=%.3f, "
                    "consecutive=%d, time=%.1fs",
                    composite, score.audio_energy, score.video_motion,
                    consecutive_high, self.current_time,
                )
                last_trigger = time.time()
                consecutive_high = 0

    async def _state_watcher_loop(self):
        """Stream state değişimlerini izle, adaptive FPS'i güncelle.
        Composite score bazlı otomatik state transition."""
        STEP = 2
        last_state = "steady"
        high_energy_streak = 0

        while self._running:
            await asyncio.sleep(STEP)
            score = self._score_buffer.latest
            if not score:
                continue

            composite = score.composite_score

            # State transition logic
            if composite >= 0.8:
                new_state = "peak_moment"
                high_energy_streak += 1
            elif composite >= 0.6:
                new_state = "high_energy"
                high_energy_streak += 1
            else:
                new_state = "steady"
                high_energy_streak = 0

            if new_state != last_state:
                logger.info(
                    "Stream state değişti: %s → %s (composite=%.2f)",
                    last_state, new_state, composite,
                )
                last_state = new_state
                self._video_buffer.update_from_state(new_state)

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def current_time(self) -> float:
        """Stream başlangıcından itibaren saniye."""
        return time.time() - self._start_time if self._start_time else 0.0

    def get_status(self) -> Dict[str, Any]:
        pipeline_stats = self._pipeline.stats if self._pipeline else {}
        chat_status = self._chat_producer.get_status() if self._chat_producer else {}
        return {
            "running": self._running,
            "uptime_seconds": round(self.current_time, 1),
            "stream_id": self._stream_id,
            "audio": {
                "ring_buffer_size": self._audio_ring.size if self._audio_ring else 0,
                "ring_buffer_capacity": self._audio_ring.capacity if self._audio_ring else 0,
                "streaming_audio_running": self._streaming_audio.is_running if self._streaming_audio else False,
            },
            "video": {
                "frame_count": self._video_buffer.count,
                "total_received": self._video_buffer.total_frames_received,
                "total_dropped": self._video_buffer.total_frames_dropped,
                "current_fps": self._video_buffer.current_fps,
                "actual_fps": round(self._video_buffer.count / max(1, self.current_time), 1),
            },
            "chat": {
                "total_messages": chat_status.get("total_messages", 0),
                "velocity": chat_status.get("velocity", {}),
                "backoff": chat_status.get("backoff", {}),
            },
            "pipeline": {
                "processed_frames": pipeline_stats.get("processed_frames", 0),
                "events_triggered": pipeline_stats.get("events_triggered", 0),
                "is_running": pipeline_stats.get("is_running", False),
            },
            "scores": {
                "count": len(self._score_buffer.scores),
                "latest_composite": self._score_buffer.latest.composite_score
                if self._score_buffer.latest else 0,
            },
            "pipe_healthy": self._ffmpeg._running if self._ffmpeg else False,
            "reconnect_count": self._ffmpeg._reconnect_count if self._ffmpeg else 0,
        }

    def on_audio(self, callback: Callable):
        """Ses analiz callback'i kaydet."""
        self._on_audio_callbacks.append(callback)

    def on_video(self, callback: Callable):
        """Video analiz callback'i kaydet."""
        self._on_video_callbacks.append(callback)

    def on_score(self, callback: Callable):
        """Füzyon skor callback'i kaydet."""
        self._on_score_callbacks.append(callback)

    def on_clip_trigger(self, callback: Callable):
        """Klip tetikleme callback'i kaydet (pipeline'dan gelen trigger'lar için)."""
        self._on_clip_callbacks.append(callback)


# ── Singleton ────────────────────────────────────────────────────────────────

live_stream_processor = LiveStreamProcessor()
