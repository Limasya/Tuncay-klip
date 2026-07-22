"""
Stream Capture Microservice
────────────────────────────
Captures HLS stream via FFmpeg, stores frames in rolling buffer,
publishes FRAME_EXTRACTED events for downstream analysis.

Flow: HLS URL → FFmpeg → Raw BGR → Rolling Buffer → Kafka/EventBus
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import cv2
import numpy as np

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import (
    EventType, FrameAnalysisResult, SystemEvent, StreamState, StreamInfo,
)

logger = logging.getLogger("stream_capture")


# ─── Frame ────────────────────────────────────────────────────

@dataclass
class Frame:
    """Single video frame with metadata."""
    frame_id: str
    timestamp: datetime
    image: np.ndarray            # BGR, shape=(H, W, 3)
    width: int
    height: int
    fps: float
    stream_time_seconds: float

    @property
    def memory_mb(self) -> float:
        return self.image.nbytes / (1024 * 1024)


# ─── Rolling Buffer ──────────────────────────────────────────

class RollingBuffer:
    """
    Ring buffer for storing recent frames.

    Memory budget (720p, 2 FPS, 30s):
      1280×720×3 = 2.8 MB/frame × 60 frames = 168 MB
    """

    def __init__(
        self,
        max_seconds: int = 30,
        target_fps: int = 2,
    ):
        self.max_seconds = max_seconds
        self.target_fps = target_fps
        self.max_frames = max_seconds * target_fps
        self._frames: deque[Frame] = deque(maxlen=self.max_frames)

    def add(self, frame: Frame):
        self._frames.append(frame)

    def get_range(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> list[Frame]:
        frames = list(self._frames)
        if start_time and end_time:
            return [f for f in frames if start_time <= f.timestamp <= end_time]
        return frames

    def get_latest(self, n: int = 1) -> list[Frame]:
        return list(self._frames)[-n:]

    def get_by_stream_time(
        self,
        start_sec: float,
        end_sec: float,
    ) -> list[Frame]:
        return [
            f for f in self._frames
            if start_sec <= f.stream_time_seconds <= end_sec
        ]

    @property
    def oldest(self) -> Optional[Frame]:
        return self._frames[0] if self._frames else None

    @property
    def newest(self) -> Optional[Frame]:
        return self._frames[-1] if self._frames else None

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    @property
    def duration_seconds(self) -> float:
        if len(self._frames) < 2:
            return 0.0
        return (self._frames[-1].timestamp - self._frames[0].timestamp).total_seconds()

    @property
    def memory_usage_mb(self) -> float:
        if not self._frames:
            return 0.0
        return self._frames[0].memory_mb * len(self._frames)


# ─── Backpressure Manager ────────────────────────────────────

class BackpressureManager:
    """Dynamically adjusts frame rate based on queue pressure."""

    def __init__(self, max_queue_size: int = 10):
        self.max_queue_size = max_queue_size
        self._drop_counter = 0
        self._drop_rate = 0

    def should_process(self, queue_size: int) -> bool:
        if queue_size > self.max_queue_size * 0.8:
            self._drop_rate = min(self._drop_rate + 1, 5)
        elif queue_size < self.max_queue_size * 0.3:
            self._drop_rate = max(self._drop_rate - 1, 0)

        if self._drop_rate > 0:
            self._drop_counter += 1
            return self._drop_counter % (self._drop_rate + 1) == 0
        return True


# ─── Stream Capture Engine ───────────────────────────────────

class AudioBuffer:
    """Rolling buffer for raw PCM audio chunks."""

    def __init__(self, max_seconds: int = 30, sample_rate: int = 16000):
        self.max_seconds = max_seconds
        self.sample_rate = sample_rate
        # Store 1-second chunks
        self._chunks: deque[tuple[float, np.ndarray]] = deque(
            maxlen=max_seconds
        )

    def add(self, timestamp: float, samples: np.ndarray):
        self._chunks.append((timestamp, samples))

    def get_range(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> list[tuple[float, np.ndarray]]:
        if start_time is None or end_time is None:
            return list(self._chunks)
        return [(ts, s) for ts, s in self._chunks if start_time <= ts <= end_time]

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def duration_seconds(self) -> float:
        return float(len(self._chunks))

    @property
    def memory_usage_mb(self) -> float:
        if not self._chunks:
            return 0.0
        return sum(s.nbytes for _, s in self._chunks) / (1024 * 1024)


class StreamCaptureService:
    """
    Captures HLS/RTMP stream using FFmpeg subprocess.

    ┌────────────────────────────────────────────────┐
    │ FFmpeg Subprocess (Video)                       │
    │                                                 │
    │ Input: HLS URL (-i https://...m3u8)            │
    │ Filter: fps=2 (-vf fps=2)                      │
    │ Output: Raw BGR pipe (-f rawvideo -pix_fmt     │
    │         bgr24)                                  │
    │                                                 │
    │ stdout ──► numpy.frombuffer() ──► Frame        │
    └────────────────────────────────────────────────┘

    ┌────────────────────────────────────────────────┐
    │ FFmpeg Subprocess (Audio)                       │
    │                                                 │
    │ Input: same HLS URL                            │
    │ Output: PCM s16le, 16kHz, mono                 │
    │                                                 │
    │ stdout ──► numpy int16 → float32 ──► chunk     │
    └────────────────────────────────────────────────┘
    """

    def __init__(
        self,
        stream_url: str,
        target_fps: int = 2,
        buffer_seconds: int = 30,
        resolution: Optional[tuple[int, int]] = None,
        event_bus: Optional[EventBus] = None,
        sample_rate: int = 16000,
    ):
        self.stream_url = stream_url
        self.target_fps = target_fps
        self.buffer_seconds = buffer_seconds
        self.resolution = resolution or (1280, 720)
        self.sample_rate = sample_rate

        self.buffer = RollingBuffer(
            max_seconds=buffer_seconds,
            target_fps=target_fps,
        )
        self.audio_buffer = AudioBuffer(
            max_seconds=buffer_seconds,
            sample_rate=sample_rate,
        )
        self.backpressure = BackpressureManager()
        self.event_bus = event_bus or get_event_bus()

        self._process: Optional[subprocess.Popen] = None
        self._audio_process: Optional[subprocess.Popen] = None
        self._is_running = False
        self._frame_counter = 0
        self._start_time: Optional[datetime] = None
        self._stream_info: Optional[StreamInfo] = None

        # Health monitoring
        self._health_task: Optional[asyncio.Task] = None
        self._last_frame_time: Optional[float] = None
        self._reconnect_count = 0
        self._max_reconnect_attempts = 10
        self._reconnect_delay = 5.0  # seconds, doubles on each failure

        # Callbacks
        self._on_frame_callbacks: list[Callable] = []
        self._on_audio_callbacks: list[Callable] = []

    @property
    def is_capturing(self) -> bool:
        return self._is_running

    def on_frame(self, callback: Callable):
        """Register a callback for each new frame."""
        self._on_frame_callbacks.append(callback)

    def on_audio_chunk(self, callback: Callable):
        """Register a callback for each 1-second audio chunk."""
        self._on_audio_callbacks.append(callback)

    async def start(self, stream_url: Optional[str] = None) -> StreamInfo:
        """Start capturing the stream."""
        if self._is_running:
            raise RuntimeError("Capture already running")

        url = stream_url or self.stream_url
        if not url:
            raise ValueError("No stream URL provided")

        # Build and start FFmpeg
        cmd = self._build_ffmpeg_command(url)
        logger.info(f"Starting FFmpeg capture from {url}")

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=10**8,
        )

        self._is_running = True
        self._start_time = datetime.now(timezone.utc)
        self._stream_info = StreamInfo(
            platform="kick",
            channel_slug=self.stream_url.split("/")[-1] if "/" in self.stream_url else "unknown",
            started_at=self._start_time,
            state=StreamState.STARTING,
        )

        # Publish stream started event
        await self.event_bus.publish_quick(
            event_type=EventType.STREAM_STARTED,
            payload=self._stream_info.model_dump(mode="json"),
            source_service="stream-capture",
        )

        # Start reading in background
        asyncio.create_task(self._read_loop())

        # Start audio capture
        asyncio.create_task(self._audio_read_loop())

        # Start health monitor
        self._health_task = asyncio.create_task(self._health_monitor())

        logger.info("Stream capture started (video + audio + health monitor)")
        return self._stream_info

    async def stop(self):
        """Stop the capture gracefully."""
        self._is_running = False

        # Stop health monitor
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

        if self._audio_process:
            self._audio_process.terminate()
            try:
                self._audio_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._audio_process.kill()
            self._audio_process = None

        if self._stream_info:
            self._stream_info.state = StreamState.OFFLINE
            await self.event_bus.publish_quick(
                event_type=EventType.STREAM_ENDED,
                payload={"stream_id": self._stream_info.stream_id},
                source_service="stream-capture",
            )

        logger.info(f"Stream capture stopped. Frames captured: {self._frame_counter}")

    def _build_ffmpeg_command(self, url: str) -> list[str]:
        w, h = self.resolution
        return [
            "ffmpeg",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", url,
            "-vf", f"fps={self.target_fps},scale={w}:{h}",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-an",
            "pipe:1",
        ]

    def _build_audio_ffmpeg_command(self, url: str) -> list[str]:
        """Build FFmpeg command for audio-only PCM extraction."""
        return [
            "ffmpeg",
            "-fflags", "nobuffer",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", url,
            "-vn",                  # no video
            "-acodec", "pcm_s16le", # 16-bit PCM
            "-ar", str(self.sample_rate),
            "-ac", "1",             # mono
            "-f", "s16le",
            "-v", "quiet",
            "pipe:1",
        ]

    async def _audio_read_loop(self):
        """Read PCM audio from a separate FFmpeg subprocess."""
        url = self.stream_url
        chunk_samples = self.sample_rate  # 1 second = 16000 samples
        chunk_bytes = chunk_samples * 2   # 16-bit = 2 bytes/sample

        cmd = self._build_audio_ffmpeg_command(url)
        logger.info(f"Starting FFmpeg audio capture from {url}")

        try:
            self._audio_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=chunk_bytes * 4,
            )
        except Exception as e:
            logger.error(f"Failed to start audio FFmpeg: {e}")
            return

        while self._is_running and self._audio_process and self._audio_process.poll() is None:
            try:
                raw = await asyncio.get_event_loop().run_in_executor(
                    None, self._audio_process.stdout.read, chunk_bytes
                )
            except Exception:
                break

            if not raw or len(raw) < chunk_bytes:
                logger.warning("Audio stream ended or incomplete chunk")
                break

            # PCM 16-bit → numpy float32 normalized [-1, 1]
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            samples = samples / 32768.0

            now = datetime.now(timezone.utc)
            stream_time = (
                (now - self._start_time).total_seconds()
                if self._start_time else 0.0
            )

            # Store in audio buffer
            self.audio_buffer.add(stream_time, samples.copy())

            # Notify callbacks
            for cb in self._on_audio_callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(samples.copy(), stream_time)
                    else:
                        cb(samples.copy(), stream_time)
                except Exception as e:
                    logger.error(f"Audio callback error: {e}")

        logger.info("Audio capture loop ended")

    async def _read_loop(self):
        """Read raw frames from FFmpeg pipe."""
        w, h = self.resolution
        frame_size = w * h * 3

        while self._is_running and self._process and self._process.poll() is None:
            try:
                raw_data = await asyncio.get_event_loop().run_in_executor(
                    None, self._process.stdout.read, frame_size
                )
            except Exception:
                break

            if not raw_data or len(raw_data) < frame_size:
                logger.warning("Stream ended or incomplete frame")
                break

            # Update last frame time for health monitor
            self._last_frame_time = time.time()

            # Backpressure check
            if not self.backpressure.should_process(self.buffer.frame_count):
                continue

            # Convert to numpy
            frame_array = np.frombuffer(raw_data, dtype=np.uint8).reshape((h, w, 3))
            now = datetime.now(timezone.utc)

            frame = Frame(
                frame_id=f"f{self._frame_counter:08d}",
                timestamp=now,
                image=frame_array.copy(),  # Copy to avoid buffer reuse issues
                width=w,
                height=h,
                fps=self.target_fps,
                stream_time_seconds=(now - self._start_time).total_seconds()
                    if self._start_time else 0.0,
            )

            # Store in buffer
            self.buffer.add(frame)
            self._frame_counter += 1

            # Publish event (no image data — just metadata)
            await self.event_bus.publish_quick(
                event_type=EventType.FRAME_EXTRACTED,
                payload={
                    "frame_id": frame.frame_id,
                    "timestamp": frame.timestamp.isoformat(),
                    "width": frame.width,
                    "height": frame.height,
                    "stream_time_seconds": frame.stream_time_seconds,
                },
                source_service="stream-capture",
                stream_id=self._stream_info.stream_id if self._stream_info else "",
            )

            # Notify callbacks
            for cb in self._on_frame_callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(frame)
                    else:
                        cb(frame)
                except Exception as e:
                    logger.error(f"Frame callback error: {e}")

        # Stream ended
        if self._is_running:
            logger.info("FFmpeg video process ended (health monitor will reconnect)")
            self._last_frame_time = None

    async def _health_monitor(self):
        """
        Periodic health check for the stream capture.

        Monitors:
        - Video FFmpeg process alive
        - Audio FFmpeg process alive
        - Frame rate (detect stalled captures)
        - Auto-reconnect with exponential backoff
        """
        check_interval = 10.0  # Check every 10 seconds
        stall_threshold = 15.0  # No frames in 15s = stalled

        while self._is_running:
            await asyncio.sleep(check_interval)

            if not self._is_running:
                break

            video_ok = self._process is not None and self._process.poll() is None
            audio_ok = self._audio_process is not None and self._audio_process.poll() is None

            # Check for stalled capture (no frames recently)
            now = time.time()
            stalled = False
            if self._last_frame_time and (now - self._last_frame_time) > stall_threshold:
                stalled = True

            if not video_ok or not audio_ok or stalled:
                reason = []
                if not video_ok:
                    reason.append("video_ffmpeg_dead")
                if not audio_ok:
                    reason.append("audio_ffmpeg_dead")
                if stalled:
                    reason.append("frame_stall")

                logger.warning(
                    f"Stream unhealthy: {', '.join(reason)} — "
                    f"attempting reconnect #{self._reconnect_count + 1}"
                )

                # Publish error event
                await self.event_bus.publish_quick(
                    event_type=EventType.STREAM_ERROR,
                    payload={
                        "reason": ", ".join(reason),
                        "reconnect_attempt": self._reconnect_count + 1,
                    },
                    source_service="stream-capture",
                    stream_id=self._stream_info.stream_id if self._stream_info else "",
                )

                # Reconnect
                if self._reconnect_count >= self._max_reconnect_attempts:
                    logger.error(
                        f"Max reconnect attempts ({self._max_reconnect_attempts}) reached. Giving up."
                    )
                    self._is_running = False
                    break

                await self._reconnect()

    async def _reconnect(self):
        """Reconnect to the stream with exponential backoff."""
        self._reconnect_count += 1
        delay = min(self._reconnect_delay * (2 ** (self._reconnect_count - 1)), 60.0)

        logger.info(f"Reconnecting in {delay:.1f}s (attempt {self._reconnect_count})...")
        await asyncio.sleep(delay)

        if not self._is_running:
            return

        # Kill existing processes
        for proc in (self._process, self._audio_process):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()

        self._process = None
        self._audio_process = None

        # Restart video FFmpeg
        url = self.stream_url
        try:
            cmd = self._build_ffmpeg_command(url)
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=10**8,
            )
            logger.info("Video FFmpeg restarted")

            # Restart audio FFmpeg
            audio_cmd = self._build_audio_ffmpeg_command(url)
            self._audio_process = subprocess.Popen(
                audio_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=self.sample_rate * 2 * 4,
            )
            logger.info("Audio FFmpeg restarted")

            # Reset stall timer
            self._last_frame_time = time.time()

            logger.info(f"Reconnect #{self._reconnect_count} successful")

        except Exception as e:
            logger.error(f"Reconnect failed: {e}")

    def extract_clip(
        self,
        event_time: datetime,
        pre_seconds: float = 5.0,
        post_seconds: float = 5.0,
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        Extract a clip from the rolling buffer (video + audio).

        Video frames come from RollingBuffer, audio from AudioBuffer.
        They are muxed together via FFmpeg.
        """
        clip_start = event_time - timedelta(seconds=pre_seconds)
        clip_end = event_time + timedelta(seconds=post_seconds)

        frames = self.buffer.get_range(start_time=clip_start, end_time=clip_end)

        if len(frames) < 3:
            logger.warning(f"Insufficient frames for clip: {len(frames)}")
            return None

        if not output_path:
            os.makedirs("data/clips", exist_ok=True)
            ts = int(time.time())
            output_path = f"data/clips/clip_{ts}.mp4"

        # ── Step 1: Write raw video frames to temp AVI ──
        temp_video = output_path + ".temp_video.avi"
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(
            temp_video, fourcc, self.target_fps,
            (frames[0].width, frames[0].height),
        )
        for frame in frames:
            writer.write(frame.image)
        writer.release()

        # ── Step 2: Write audio to temp WAV ──
        temp_audio = output_path + ".temp_audio.wav"
        audio_start_sec = (clip_start - self._start_time).total_seconds() if self._start_time else 0
        audio_end_sec = (clip_end - self._start_time).total_seconds() if self._start_time else 0
        audio_chunks = self.audio_buffer.get_range(audio_start_sec, audio_end_sec)
        has_audio = len(audio_chunks) > 0

        if has_audio:
            import wave
            all_samples = np.concatenate([s for _, s in audio_chunks])
            pcm = (all_samples * 32768).clip(-32768, 32767).astype(np.int16)
            try:
                with wave.open(temp_audio, "w") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(self.sample_rate)
                    wf.writeframes(pcm.tobytes())
            except Exception as e:
                logger.warning(f"Audio WAV write failed: {e}")
                has_audio = False

        # ── Step 3: Mux video + audio with FFmpeg ──
        if has_audio:
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", temp_video,
                    "-i", temp_audio,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-c:a", "aac", "-b:a", "128k",
                    "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    "-shortest",
                    output_path,
                ],
                capture_output=True, timeout=120,
            )
        else:
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", temp_video,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    output_path,
                ],
                capture_output=True, timeout=120,
            )

        # Cleanup temp files
        for tmp in (temp_video, temp_audio):
            if os.path.exists(tmp):
                os.remove(tmp)

        if result.returncode == 0 and os.path.exists(output_path):
            file_size = os.path.getsize(output_path) / (1024 * 1024)
            logger.info(
                f"Clip extracted: {output_path} "
                f"({len(frames)} frames, audio={'yes' if has_audio else 'no'}, "
                f"{file_size:.1f} MB)"
            )
            return output_path

        logger.error(f"FFmpeg clip extraction failed: {result.stderr.decode()[:500]}")
        return None

    def get_status(self) -> dict:
        video_alive = self._process is not None and self._process.poll() is None
        audio_alive = self._audio_process is not None and self._audio_process.poll() is None
        seconds_since_frame = (
            round(time.time() - self._last_frame_time, 1)
            if self._last_frame_time else None
        )
        return {
            "is_capturing": self._is_running,
            "frames_captured": self._frame_counter,
            "buffer_frames": self.buffer.frame_count,
            "buffer_duration_s": round(self.buffer.duration_seconds, 1),
            "buffer_memory_mb": round(self.buffer.memory_usage_mb, 1),
            "audio_buffer_chunks": self.audio_buffer.chunk_count,
            "audio_buffer_duration_s": round(self.audio_buffer.duration_seconds, 1),
            "audio_buffer_memory_mb": round(self.audio_buffer.memory_usage_mb, 1),
            "health": {
                "video_ffmpeg": "alive" if video_alive else "dead",
                "audio_ffmpeg": "alive" if audio_alive else "dead",
                "seconds_since_last_frame": seconds_since_frame,
                "reconnect_count": self._reconnect_count,
            },
            "stream_url": self.stream_url,
            "target_fps": self.target_fps,
            "resolution": f"{self.resolution[0]}x{self.resolution[1]}",
        }
