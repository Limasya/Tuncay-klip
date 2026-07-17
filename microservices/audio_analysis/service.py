"""
Audio Analysis Microservice
────────────────────────────
Processes audio chunks: energy analysis, spike detection, VAD.

Flow: Audio Chunk → Feature Extraction → Spike Detection → Events
"""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime
from typing import Optional

import numpy as np

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import EventType, AudioFeatures, AudioSpikeEvent

try:
    from services.audio_ai import (
        SpeechEmotionRecognizer,
        AudioEventClassifier,
        CrowdReactionDetector,
        MusicDetector,
    )
    _AUDIO_AI_AVAILABLE = True
except ImportError as e:
    logger.warning("Audio AI module not available: %s", e)
    _AUDIO_AI_AVAILABLE = False

logger = logging.getLogger("audio_analysis")


class AudioFeatureExtractor:
    """
    Extracts features from 1-second audio chunks.

    Features: RMS energy, ZCR, spectral centroid, spectral rolloff.
    These feed into spike detection and emotion analysis.
    """

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._energy_history: deque[float] = deque(maxlen=60)
        self._zcr_history: deque[float] = deque(maxlen=60)

    def extract(self, audio_chunk: np.ndarray) -> AudioFeatures:
        if len(audio_chunk) == 0:
            return AudioFeatures()

        # RMS Energy
        rms = float(np.sqrt(np.mean(audio_chunk.astype(np.float64) ** 2)))

        # Zero Crossing Rate
        signs = np.sign(audio_chunk.astype(np.float64))
        zcr = float(np.mean(np.abs(np.diff(signs)) > 0))

        # Spectral centroid (simplified — no librosa dependency)
        fft = np.abs(np.fft.rfft(audio_chunk.astype(np.float64)))
        freqs = np.fft.rfftfreq(len(audio_chunk), 1.0 / self.sample_rate)
        if np.sum(fft) > 0:
            spectral_centroid = float(np.sum(freqs * fft) / np.sum(fft))
        else:
            spectral_centroid = 0.0

        # Spectral rolloff
        cumsum = np.cumsum(fft)
        total = cumsum[-1] if len(cumsum) > 0 else 1.0
        rolloff_idx = np.searchsorted(cumsum, 0.85 * total)
        spectral_rolloff = float(freqs[min(rolloff_idx, len(freqs) - 1)])

        # Spike detection
        self._energy_history.append(rms)
        self._zcr_history.append(zcr)

        is_spike, magnitude = self._detect_spike(rms)

        return AudioFeatures(
            rms_energy=rms,
            zero_crossing_rate=zcr,
            spectral_centroid=spectral_centroid,
            spectral_rolloff=spectral_rolloff,
            is_spike=is_spike,
            spike_magnitude=magnitude,
        )

    def _detect_spike(self, current_rms: float) -> tuple[bool, float]:
        if len(self._energy_history) < 10:
            return False, 0.0

        baseline = np.array(list(self._energy_history)[:-1])
        mean = np.mean(baseline)
        std = np.std(baseline)

        if std < 1e-8:
            return False, 0.0

        z_score = (current_rms - mean) / std
        is_spike = z_score > 2.0
        magnitude = max(0.0, min(z_score / 5.0, 1.0))

        return is_spike, magnitude


class AudioSpikeDetector:
    """Detects sustained audio spikes (screams/yells/celebrations)."""

    def __init__(
        self,
        min_duration: float = 0.5,
        max_duration: float = 5.0,
    ):
        self.min_duration = min_duration
        self.max_duration = max_duration
        self._spike_start: Optional[float] = None
        self._spike_chunks: list[AudioFeatures] = []

    def process(self, features: AudioFeatures, timestamp: float) -> Optional[AudioSpikeEvent]:
        if features.is_spike:
            if self._spike_start is None:
                self._spike_start = timestamp
            self._spike_chunks.append(features)
        elif self._spike_start is not None:
            duration = timestamp - self._spike_start
            if self.min_duration <= duration <= self.max_duration:
                event = AudioSpikeEvent(
                    start_time=self._spike_start,
                    end_time=timestamp,
                    duration=duration,
                    peak_magnitude=max(c.spike_magnitude for c in self._spike_chunks),
                    avg_energy=float(np.mean([c.rms_energy for c in self._spike_chunks])),
                    chunk_count=len(self._spike_chunks),
                )
                self._spike_start = None
                self._spike_chunks = []
                return event
            self._spike_start = None
            self._spike_chunks = []
        return None


class AudioAnalysisService:
    """
    Main audio analysis service.
    Subscribes to audio chunk events, publishes analysis results.

    Enhanced v2 pipeline:
    1. Feature Extraction (energy, ZCR, spectral)
    2. Spike Detection (sustained audio bursts)
    3. Speech Emotion Recognition
    4. Audio Event Classification (scream, laugh, clap, etc.)
    5. Crowd Reaction Detection (cheer, boo)
    6. Music Detection (presence, genre)
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_bus = event_bus or get_event_bus()
        self.extractor = AudioFeatureExtractor()
        self.spike_detector = AudioSpikeDetector()

        if _AUDIO_AI_AVAILABLE:
            self.speech_emotion = SpeechEmotionRecognizer()
            self.event_classifier = AudioEventClassifier()
            self.crowd_detector = CrowdReactionDetector()
            self.music_detector = MusicDetector()
        else:
            self.speech_emotion = None
            self.event_classifier = None
            self.crowd_detector = None
            self.music_detector = None

        self._metrics = {
            "chunks_analyzed": 0,
            "spikes_detected": 0,
            "avg_rms": 0.0,
            "emotions_detected": 0,
            "events_classified": 0,
            "crowd_reactions": 0,
        }

    async def analyze_chunk(self, audio_data: np.ndarray) -> AudioFeatures:
        features = self.extractor.extract(audio_data)
        now = time.time()

        spike = self.spike_detector.process(features, now)
        if spike:
            self._metrics["spikes_detected"] += 1
            await self.event_bus.publish_quick(
                EventType.AUDIO_SPIKE,
                spike.model_dump(mode="json"),
                source_service="audio-analysis",
            )

        await self.event_bus.publish_quick(
            EventType.AUDIO_FEATURES,
            features.model_dump(mode="json"),
            source_service="audio-analysis",
        )

        if self.speech_emotion is not None:
            emotion = self.speech_emotion.recognize(audio_data)
            if emotion.get("confidence", 0) > 0.4:
                self._metrics["emotions_detected"] += 1
                await self.event_bus.publish_quick(
                    EventType.SPEECH_EMOTION,
                    {"timestamp": now, **emotion},
                    source_service="audio-analysis",
                )

        if self.event_classifier is not None:
            feat_dict = {
                "rms_energy": features.rms_energy,
                "spectral_centroid": features.spectral_centroid,
                "zero_crossing_rate": features.zero_crossing_rate,
            }
            events = self.event_classifier.classify(audio_data, feat_dict)
            if events:
                self._metrics["events_classified"] += len(events)
                for evt in events:
                    await self.event_bus.publish_quick(
                        EventType.AUDIO_SPIKE,
                        {"timestamp": now, "audio_event": evt},
                        source_service="audio-analysis",
                    )

        if self.crowd_detector is not None:
            crowd = self.crowd_detector.detect(audio_data, {})
            if crowd:
                self._metrics["crowd_reactions"] += 1
                await self.event_bus.publish_quick(
                    EventType.CHAT_SPIKE,
                    {"timestamp": now, "crowd": crowd},
                    source_service="audio-analysis",
                )

        if self.music_detector is not None:
            music = self.music_detector.analyze(audio_data, {})
            if music.get("music_present") and music.get("confidence", 0) > 0.5:
                await self.event_bus.publish_quick(
                    EventType.SPEECH_EMOTION,
                    {"timestamp": now, "music": music},
                    source_service="audio-analysis",
                )

        self._metrics["chunks_analyzed"] += 1
        self._metrics["avg_rms"] = (
            self._metrics["avg_rms"] * 0.9 + features.rms_energy * 0.1
        )

        return features

    def get_status(self) -> dict:
        status = dict(self._metrics)
        if self.speech_emotion is not None:
            status["speech_emotion"] = self.speech_emotion.get_status()
        if self.event_classifier is not None:
            status["event_classifier"] = self.event_classifier.get_status()
        if self.crowd_detector is not None:
            status["crowd_detector"] = self.crowd_detector.get_status()
        if self.music_detector is not None:
            status["music_detector"] = self.music_detector.get_status()
        return status
