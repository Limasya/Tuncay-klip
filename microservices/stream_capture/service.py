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
from datetime import datetime, timedelta
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

class StreamCaptureService:
    """
    Captures HLS/RTMP stream using FFmpeg subprocess.

    ┌────────────────────────────────────────────────┐
    │ FFmpeg Subprocess                               │
    │                                                 │
    │ Input: HLS URL (-i https://...m3u8)            │
    │ Filter: fps=2 (-vf fps=2)                      │
    │ Output: Raw BGR pipe (-f rawvideo -pix_fmt     │
    │         bgr24)                                  │
    │                                                 │
    │ stdout ──► numpy.frombuffer() ──► Frame        │
    └────────────────────────────────────────────────┘
    """

    def __init__(
        self,
        stream_url: str,
        target_fps: int = 2,
        buffer_seconds: int = 30,
        resolution: Optional[tuple[int, int]] = None,
        event_bus: Optional[EventBus] = None,
    ):
        self.stream_url = stream_url
        self.target_fps = target_fps
        self.buffer_seconds = buffer_seconds
        self.resolution = resolution or (1280, 720)

        self.buffer = RollingBuffer(
            max_seconds=buffer_seconds,
            target_fps=target_fps,
        )
        self.backpressure = BackpressureManager()
        self.event_bus = event_bus or get_event_bus()

        self._process: Optional[subprocess.Popen] = None
        self._is_running = False
        self._frame_counter = 0
        self._start_time: Optional[datetime] = None
        self._stream_info: Optional[StreamInfo] = None

        # Callbacks
        self._on_frame_callbacks: list[Callable] = []

    @property
    def is_capturing(self) -> bool:
        return self._is_running

    def on_frame(self, callback: Callable):
        """Register a callback for each new frame."""
        self._on_frame_callbacks.append(callback)

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
        self._start_time = datetime.utcnow()
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

        logger.info("Stream capture started")
        return self._stream_info

    async def stop(self):
        """Stop the capture gracefully."""
        self._is_running = False

        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

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

            # Backpressure check
            if not self.backpressure.should_process(self.buffer.frame_count):
                continue

            # Convert to numpy
            frame_array = np.frombuffer(raw_data, dtype=np.uint8).reshape((h, w, 3))
            now = datetime.utcnow()

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
            self._is_running = False
            logger.info("FFmpeg process ended")

    def extract_clip(
        self,
        event_time: datetime,
        pre_seconds: float = 5.0,
        post_seconds: float = 5.0,
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        Extract a clip from the rolling buffer.

        This is the KEY advantage: instant clip extraction from buffer.
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

        # Write raw frames to temp AVI
        temp_path = output_path + ".temp.avi"
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(
            temp_path, fourcc, self.target_fps,
            (frames[0].width, frames[0].height),
        )

        for frame in frames:
            writer.write(frame.image)
        writer.release()

        # Re-encode to MP4
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", temp_path,
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                output_path,
            ],
            capture_output=True, timeout=120,
        )

        # Cleanup
        if os.path.exists(temp_path):
            os.remove(temp_path)

        if result.returncode == 0 and os.path.exists(output_path):
            file_size = os.path.getsize(output_path) / (1024 * 1024)
            logger.info(
                f"Clip extracted: {output_path} "
                f"({len(frames)} frames, {file_size:.1f} MB)"
            )
            return output_path

        logger.error(f"FFmpeg clip extraction failed: {result.stderr.decode()[:500]}")
        return None

    def get_status(self) -> dict:
        return {
            "is_capturing": self._is_running,
            "frames_captured": self._frame_counter,
            "buffer_frames": self.buffer.frame_count,
            "buffer_duration_s": round(self.buffer.duration_seconds, 1),
            "buffer_memory_mb": round(self.buffer.memory_usage_mb, 1),
            "stream_url": self.stream_url,
            "target_fps": self.target_fps,
            "resolution": f"{self.resolution[0]}x{self.resolution[1]}",
        }
