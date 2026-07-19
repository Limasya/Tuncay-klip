"""
Unified AI Analysis Service — Tüm motorları birleştiren tek analiz katmanı
══════════════════════════════════════════════════════════════════════════════
Motorlar:
  - C++ Signal Engine (FFT, beat, motion, correlation)
  - YOLOv8 Faster R-CNN (object/action detection)
  - SceneDetectionEngine (FFmpeg scene boundaries)
  - EmotionDetector (DeepFace facial emotions)
  - AudioAnalyzer (FFmpeg ebur128 loud peaks)
  - LLM Reasoner (Groq Llama-3 semantic highlights)

Kullanım:
    from services.ai_analysis import ai_analyzer
    result = await ai_analyzer.analyze_clip(video_path)
    result = await ai_analyzer.analyze_vod(vod_path, semantic_clips)
"""
from __future__ import annotations

import asyncio
import logging
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ai_analysis")

# ── Motorları import et (opsiyonel — hepsi graceful fallback) ────────────────

try:
    from signal_engine.python.signal_client import signal_engine as cpp_engine
except Exception:
    cpp_engine = None

try:
    from services.action_recognizer import action_recognizer
except Exception:
    action_recognizer = None

try:
    from services.scene_detection import SceneDetectionEngine
    _scene_detect = SceneDetectionEngine()
except Exception:
    _scene_detect = None

try:
    from services.emotion_detector import emotion_detector
except Exception:
    emotion_detector = None

try:
    from services.audio_analyzer import audio_analyzer
except Exception:
    audio_analyzer = None


# ── Sonuç tipleri ─────────────────────────────────────────────────────────────

@dataclass
class AudioFeatures:
    bpm: float = 0.0
    beat_count: int = 0
    energy: float = 0.0
    peak_amplitude: float = 0.0
    spectral_centroid: float = 0.0
    duration_sec: float = 0.0
    loud_peaks: List[Dict[str, float]] = field(default_factory=list)
    beats: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class VideoFeatures:
    scene_count: int = 0
    avg_motion: float = 0.0
    motion_vectors: List[Dict[str, Any]] = field(default_factory=list)
    scene_changes: List[Dict[str, Any]] = field(default_factory=list)
    action_score: float = 0.0
    action_spikes: List[Dict[str, float]] = field(default_factory=list)


@dataclass
class EmotionFeatures:
    dominant_emotion: str = "neutral"
    viral_weight: float = 0.0
    emotion_distribution: Dict[str, int] = field(default_factory=dict)
    viral_spikes: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ViralMoment:
    timestamp: float
    score: float
    audio_energy: float = 0.0
    visual_motion: float = 0.0
    is_beat_drop: bool = False
    is_scene_change: bool = False
    reason: str = ""


@dataclass
class ClipAnalysis:
    path: str = ""
    audio: AudioFeatures = field(default_factory=AudioFeatures)
    video: VideoFeatures = field(default_factory=VideoFeatures)
    emotion: EmotionFeatures = field(default_factory=EmotionFeatures)
    viral_moments: List[ViralMoment] = field(default_factory=list)
    viral_score: float = 0.0
    score_breakdown: Dict[str, float] = field(default_factory=dict)
    available_engines: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "viral_score": round(self.viral_score, 2),
            "score_breakdown": {k: round(v, 2) for k, v in self.score_breakdown.items()},
            "audio": {
                "bpm": self.audio.bpm,
                "beat_count": self.audio.beat_count,
                "energy": round(self.audio.energy, 2),
                "peak_amplitude": round(self.audio.peak_amplitude, 4),
                "spectral_centroid": round(self.audio.spectral_centroid, 2),
                "loud_peak_count": len(self.audio.loud_peaks),
            },
            "video": {
                "scene_count": self.video.scene_count,
                "avg_motion": round(self.video.avg_motion, 4),
                "action_score": round(self.video.action_score, 2),
                "action_spike_count": len(self.video.action_spikes),
            },
            "emotion": {
                "dominant": self.emotion.dominant_emotion,
                "viral_weight": round(self.emotion.viral_weight, 2),
                "distribution": self.emotion.emotion_distribution,
            },
            "viral_moments": [
                {
                    "timestamp": round(m.timestamp, 2),
                    "score": round(m.score, 2),
                    "reason": m.reason,
                }
                for m in self.viral_moments[:5]
            ],
            "available_engines": self.available_engines,
        }


# ── Ana analiz servisi ────────────────────────────────────────────────────────

class AIAnalyzer:
    """Tüm AI motorlarını tek bir analiz passesinde çalıştırır."""

    def __init__(self):
        self.temp_dir = Path("data/temp_clips")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _engines(self) -> List[str]:
        engines = []
        if cpp_engine and cpp_engine.available:
            engines.append("cpp_signal_engine")
        if action_recognizer:
            engines.append("yolov8_action")
        if _scene_detect:
            engines.append("scene_detect")
        if emotion_detector:
            engines.append("emotion_detector")
        if audio_analyzer:
            engines.append("audio_analyzer")
        return engines

    async def analyze_clip(self, video_path: str) -> ClipAnalysis:
        """Tek bir klipi tüm motorlarla paralel analiz et."""
        result = ClipAnalysis(path=video_path, available_engines=self._engines)
        if not Path(video_path).exists():
            logger.warning("Klip bulunamadi: %s", video_path)
            return result

        logger.info("Analiz basliyor: %s (motorlar: %s)",
                     Path(video_path).name, ", ".join(result.available_engines))

        tasks = []
        task_names = []

        # 1) C++ Signal Engine — audio analiz
        if cpp_engine and cpp_engine.available:
            tasks.append(self._analyze_audio_cpp(video_path))
            task_names.append("cpp_audio")

        # 2) C++ Signal Engine — video motion
        if cpp_engine and cpp_engine.available:
            tasks.append(self._analyze_video_cpp(video_path))
            task_names.append("cpp_video")

        # 3) C++ Signal Engine — correlation
        if cpp_engine and cpp_engine.available:
            tasks.append(self._correlate_cpp(video_path))
            task_names.append("cpp_correlate")

        # 4) YOLOv8 action detection
        if action_recognizer:
            tasks.append(self._detect_action(video_path))
            task_names.append("yolov8")

        # 5) Scene detection
        if _scene_detect:
            tasks.append(self._detect_scenes(video_path))
            task_names.append("scene")

        # 6) Emotion detection
        if emotion_detector:
            tasks.append(self._detect_emotions(video_path))
            task_names.append("emotion")

        # 7) Loud peaks
        if audio_analyzer:
            tasks.append(self._detect_loud_peaks(video_path))
            task_names.append("loud_peaks")

        if not tasks:
            logger.warning("Hicbir analiz motoru mevcut degil: %s", video_path)
            return result

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        for name, res in zip(task_names, raw_results):
            if isinstance(res, Exception):
                logger.debug("Motor %s hatasi: %s", name, res)
                continue
            if res is None:
                continue

            if name == "cpp_audio" and isinstance(res, dict) and res.get("success"):
                result.audio.bpm = res.get("beats", [{}])[0].get("bpm", 0) if res.get("beats") else 0
                result.audio.beat_count = res.get("beat_count", 0)
                result.audio.energy = res.get("total_energy", 0)
                result.audio.peak_amplitude = res.get("peak_amplitude", 0)
                result.audio.spectral_centroid = res.get("spectral_centroid", 0)
                result.audio.duration_sec = res.get("duration_sec", 0)
                result.audio.beats = res.get("beats", [])

            elif name == "cpp_video" and isinstance(res, dict) and res.get("success"):
                result.video.scene_count = res.get("scene_changes", 0)
                result.video.avg_motion = res.get("avg_motion", 0)
                result.video.scene_changes = res.get("diffs", [])
                result.video.motion_vectors = res.get("motion", [])

            elif name == "cpp_correlate" and isinstance(res, dict) and res.get("success"):
                for m in res.get("viral_moments", []):
                    result.viral_moments.append(ViralMoment(
                        timestamp=m.get("timestamp", 0),
                        score=m.get("score", 0),
                        audio_energy=m.get("audio_energy", 0),
                        visual_motion=m.get("visual_motion", 0),
                        is_beat_drop=m.get("is_beat_drop", False),
                        is_scene_change=m.get("is_scene_change", False),
                        reason=m.get("reason", ""),
                    ))

            elif name == "yolov8" and isinstance(res, dict) and res.get("success"):
                result.video.action_score = res.get("avg_objects_per_frame", 0)
                result.video.action_spikes = res.get("action_spikes", [])

            elif name == "scene" and hasattr(res, "total_scenes"):
                result.video.scene_count = max(result.video.scene_count, res.total_scenes)

            elif name == "emotion" and isinstance(res, dict) and res.get("success"):
                result.emotion.dominant_emotion = res.get("peak_emotion", "neutral")
                result.emotion.emotion_distribution = res.get("emotion_distribution", {})
                viral_spikes = res.get("viral_spikes", [])
                result.emotion.viral_spikes = viral_spikes
                if viral_spikes:
                    result.emotion.viral_weight = max(s.get("viral_weight", 0) for s in viral_spikes)

            elif name == "loud_peaks" and isinstance(res, dict) and res.get("success"):
                result.audio.loud_peaks = res.get("peaks", [])

        # ── Viral skor hesapla ─────────────────────────────────────────────
        result.viral_score, result.score_breakdown = self._compute_viral_score(result)

        logger.info("Analiz tamam: %s — viral_score=%.2f", Path(video_path).name, result.viral_score)
        return result

    async def analyze_vod(
        self,
        vod_path: str,
        semantic_clips: List[Dict[str, Any]],
        max_concurrent: int = 4,
    ) -> List[ClipAnalysis]:
        """Bir VOD'daki tüm klipleri paralel analiz et."""
        if not semantic_clips:
            return []

        from shared.utils.video_processor import video_processor
        stem = Path(vod_path).stem
        temp_dir = self.temp_dir

        # Klipleri kes (eğer henüz kesilmemişse)
        slice_tasks = []
        for idx, clip in enumerate(semantic_clips):
            out_path = str(temp_dir / f"{stem}_analysis_{idx}.mp4")
            start = clip.get("start", 0)
            end = clip.get("end", start + 30)
            dur = max(1.0, end - start)

            if Path(out_path).exists():
                slice_tasks.append(out_path)
                continue

            if video_processor.available:
                slice_tasks.append(
                    asyncio.create_task(
                        self._slice_with_rust(video_processor, vod_path, out_path, start, dur)
                    )
                )
            else:
                slice_tasks.append(
                    asyncio.create_task(
                        self._slice_with_ffmpeg(vod_path, out_path, start, dur)
                    )
                )

        sliced_paths = await asyncio.gather(*slice_tasks) if slice_tasks else []

        # Paralel analiz
        sem = asyncio.Semaphore(max_concurrent)
        async def _limited_analyze(path):
            async with sem:
                return await self.analyze_clip(path)

        analyses = await asyncio.gather(
            *[_limited_analyze(p) for p in sliced_paths if p and Path(p).exists()],
            return_exceptions=True,
        )

        return [a for a in analyses if isinstance(a, ClipAnalysis)]

    async def get_bpm_for_render(self, video_path: str) -> Optional[float]:
        """Render icin BPM degeri dondur (beat-sync icin)."""
        if not cpp_engine or not cpp_engine.available:
            return None
        try:
            result = await self._analyze_audio_cpp(video_path)
            if isinstance(result, dict) and result.get("success"):
                beats = result.get("beats", [])
                if beats:
                    return beats[0].get("bpm", 0)
        except Exception as e:
            logger.debug("BPM analiz hatasi: %s", e)
        return None

    async def get_viral_timestamps(
        self, video_path: str, min_score: float = 0.3
    ) -> List[Dict[str, Any]]:
        """Viral an zaman damgalari (render icin cut noktalari)."""
        analysis = await self.analyze_clip(video_path)
        moments = [
            {"timestamp": m.timestamp, "score": m.score, "reason": m.reason}
            for m in analysis.viral_moments
            if m.score >= min_score
        ]
        if not moments:
            # C++ correlation sonucu yoksa, loud_peaks + action_spikes kombinasyonu
            for peak in analysis.audio.loud_peaks:
                moments.append({
                    "timestamp": peak.get("start", 0),
                    "score": 0.4,
                    "reason": "loud audio peak",
                })
            for spike in analysis.video.action_spikes:
                moments.append({
                    "timestamp": spike.get("start", 0),
                    "score": 0.5,
                    "reason": "action spike (high object count)",
                })
        moments.sort(key=lambda x: x["score"], reverse=True)
        return moments

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _analyze_audio_cpp(self, video_path: str) -> Optional[Dict]:
        """C++ signal engine ile audio analiz."""
        audio_data = await asyncio.to_thread(self._extract_audio, video_path)
        if not audio_data:
            return None
        samples, sr = audio_data
        return await asyncio.to_thread(cpp_engine.analyze_audio, samples, sr)

    async def _analyze_video_cpp(self, video_path: str) -> Optional[Dict]:
        """C++ signal engine ile video motion analiz."""
        frame_data = await asyncio.to_thread(self._extract_frames, video_path, 10)
        if not frame_data:
            return None
        frames, w, h, n, fps = frame_data
        return await asyncio.to_thread(
            cpp_engine.analyze_video, frames, w, h, n, fps
        )

    async def _correlate_cpp(self, video_path: str) -> Optional[Dict]:
        """C++ signal engine ile audio-video korelasyon."""
        audio_data = await asyncio.to_thread(self._extract_audio, video_path)
        frame_data = await asyncio.to_thread(self._extract_frames, video_path, 10)
        if not audio_data or not frame_data:
            return None
        samples, sr = audio_data
        frames, w, h, n, fps = frame_data
        return await asyncio.to_thread(
            cpp_engine.correlate_signals, samples, sr, frames, w, h, n, fps
        )

    async def _detect_action(self, video_path: str) -> Any:
        return await action_recognizer.calculate_action_score(video_path)

    async def _detect_scenes(self, video_path: str) -> Any:
        return await _scene_detect.detect_scenes(video_path)

    async def _detect_emotions(self, video_path: str) -> Any:
        return await emotion_detector.analyze_video_emotions(video_path, sample_fps=0.5)

    async def _detect_loud_peaks(self, video_path: str) -> Any:
        return await audio_analyzer.get_loud_peaks(video_path)

    @staticmethod
    def _extract_audio(video_path: str) -> Optional[tuple]:
        """FFmpeg ile sesi float32 array olarak cikar (44.1kHz mono)."""
        try:
            cmd = [
                "ffmpeg", "-y", "-i", video_path,
                "-vn", "-ac", "1", "-ar", "44100",
                "-f", "f32le", "-acodec", "pcm_f32le",
                "pipe:1",
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=60)
            if proc.returncode != 0:
                return None
            raw = proc.stdout
            n = len(raw) // 4
            if n < 1024:
                return None
            samples = list(struct.unpack(f"<{n}f", raw[:n * 4]))
            return samples, 44100.0
        except Exception:
            return None

    @staticmethod
    def _extract_frames(video_path: str, max_frames: int = 10) -> Optional[tuple]:
        """FFmpeg ile RGB24 frame'leri cikar."""
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,r_frame_rate",
                 "-of", "csv=p=0", video_path],
                capture_output=True, timeout=10,
            )
            parts = probe.stdout.decode().strip().split(",")
            if len(parts) < 3:
                return None
            w, h = int(parts[0]), int(parts[1])
            fps_parts = parts[2].split("/")
            fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 else float(fps_parts[0])

            sample_fps = min(fps, max_frames * fps / 30.0)

            cmd = [
                "ffmpeg", "-y", "-i", video_path,
                "-vf", f"fps={sample_fps},scale=160:90",
                "-f", "rawvideo", "-pix_fmt", "rgb24",
                "pipe:1",
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=30)
            if proc.returncode != 0:
                return None

            raw = proc.stdout
            frame_size = 160 * 90 * 3
            n = min(len(raw) // frame_size, max_frames)
            if n < 2:
                return None
            return raw[:n * frame_size], 160, 90, n, sample_fps
        except Exception:
            return None

    async def _slice_with_rust(self, processor, input_path, output_path, start, dur):
        result = await processor.clip(
            input_path=input_path, output_path=output_path,
            start=start, duration=dur,
        )
        return output_path if result.get("success") else None

    async def _slice_with_ffmpeg(self, input_path, output_path, start, dur):
        cmd = [
            "ffmpeg", "-y", "-ss", str(start), "-i", input_path,
            "-t", str(dur), "-c:v", "copy", "-c:a", "copy", output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return output_path if Path(output_path).exists() else None

    @staticmethod
    def _compute_viral_score(analysis: ClipAnalysis) -> tuple:
        """5 boyutlu viral skor hesaplama: audio, video, emotion, correlation, peaks."""
        breakdown = {}

        # Audio skor (0-25)
        audio_score = 0.0
        if analysis.audio.bpm > 0:
            audio_score += 5.0
        if analysis.audio.energy > 3000:
            audio_score += min(10.0, analysis.audio.energy / 1000)
        if analysis.audio.beat_count >= 3:
            audio_score += 5.0
        if analysis.audio.spectral_centroid > 500:
            audio_score += min(5.0, analysis.audio.spectral_centroid / 500)
        audio_score = min(25.0, audio_score)
        breakdown["audio"] = audio_score

        # Video skor (0-25)
        video_score = 0.0
        if analysis.video.scene_count > 0:
            video_score += min(10.0, analysis.video.scene_count * 2)
        if analysis.video.avg_motion > 0.01:
            video_score += min(10.0, analysis.video.avg_motion * 100)
        if analysis.video.action_score > 1:
            video_score += min(5.0, analysis.video.action_score * 2)
        video_score = min(25.0, video_score)
        breakdown["video"] = video_score

        # Emotion skor (0-25)
        emotion_score = 0.0
        if analysis.emotion.viral_weight > 0:
            emotion_score += min(15.0, analysis.emotion.viral_weight * 5)
        if analysis.emotion.dominant_emotion not in ("neutral", "sad"):
            emotion_score += 5.0
        emotion_score = min(25.0, emotion_score)
        breakdown["emotion"] = emotion_score

        # Correlation skor (0-15)
        corr_score = 0.0
        if analysis.viral_moments:
            best = max(analysis.viral_moments, key=lambda m: m.score)
            corr_score = min(15.0, best.score * 15)
            if any(m.is_beat_drop and m.is_scene_change for m in analysis.viral_moments):
                corr_score = min(15.0, corr_score + 5)
        breakdown["correlation"] = corr_score

        # Peak skor (0-10)
        peak_score = 0.0
        if analysis.audio.loud_peaks:
            peak_score = min(10.0, len(analysis.audio.loud_peaks) * 2)
        breakdown["peaks"] = peak_score

        total = audio_score + video_score + emotion_score + corr_score + peak_score
        return total, breakdown


# ── Singleton ─────────────────────────────────────────────────────────────────

ai_analyzer = AIAnalyzer()
