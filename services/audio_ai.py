"""
Audio AI Module (IP_PART7 - AI Intelligence Expansion)

Advanced audio analysis capabilities:
  1. Speech Emotion Recognition - detect emotion from voice tone
  2. Audio Event Classification - scream, laugh, clap, gunshot, etc.
  3. Speaker Diarization - who spoke when
  4. Music Detection - background music presence and genre
  5. Audio Quality Assessment - clarity, noise level, clipping
  6. Sound FX Classification - identify specific game sounds
  7. Voice Activity Detection (enhanced) - precision VAD
  8. Crowd Reaction Detection - cheer, boo, gasp patterns

All modules work with graceful fallback when dependencies are missing.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Optional

import numpy as np

logger = logging.getLogger("audio_ai")


# ---------------------------------------------------------------------------
# Speech Emotion Recognition
# ---------------------------------------------------------------------------
class SpeechEmotionRecognizer:
    """
    Detect emotion from speech characteristics.

    Emotion classes: neutral, happy, sad, angry, fearful, surprised, disgusted.

    Features extracted from audio:
    - Pitch (fundamental frequency) variation
    - Energy envelope dynamics
    - Speech rate (syllables per second)
    - Spectral characteristics (formants, MFCC-like)
    - Voice quality (breathiness, tension)

    Falls back to energy/spectral heuristic when ML model unavailable.
    """

    EMOTIONS = ["neutral", "happy", "sad", "angry", "fearful", "surprised", "excited"]
    EMOTION_HYPE_MAP = {
        "happy": 0.7, "surprised": 0.8, "excited": 0.9,
        "angry": 0.6, "fearful": 0.5, "sad": 0.1, "neutral": 0.2,
    }

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.model = None
        self._emotion_history: deque[dict] = deque(maxlen=50)
        self._load_model()

    def _load_model(self):
        """Try to load a speech emotion model."""
        try:
            # Try HuggingFace speech emotion model
            from transformers import pipeline as hf_pipeline
            self.model = hf_pipeline(
                "audio-classification",
                model="ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition",
                device=-1,
            )
            logger.info("Speech emotion model loaded (wav2vec2)")
        except Exception:
            try:
                # Alternative: librosa-based feature extraction
                import librosa
                self._feature_extractor = librosa.feature
                logger.info("Speech emotion: using librosa features")
            except Exception:
                logger.info("Speech emotion: using heuristic fallback")

    def recognize(self, audio_chunk: np.ndarray) -> dict:
        """
        Recognize emotion from audio chunk.

        Returns: {label, confidence, hype_score, features}
        """
        if len(audio_chunk) == 0:
            return {"label": "neutral", "confidence": 0.5, "hype_score": 0.0}

        if self.model is not None:
            return self._recognize_model(audio_chunk)
        return self._recognize_heuristic(audio_chunk)

    def _recognize_model(self, audio: np.ndarray) -> dict:
        # wav2vec2 expects 16kHz mono float32
        audio_float = audio.astype(np.float32) / 32768.0
        if len(audio_float) < self.sample_rate * 0.5:
            # Pad to minimum length
            audio_float = np.pad(audio_float, (0, int(self.sample_rate * 0.5) - len(audio_float)))

        try:
            results = self.model(audio_float, sampling_rate=self.sample_rate)
            top = results[0]
            label = top["label"].lower().replace(" ", "_")
            confidence = top["score"]
        except Exception:
            return self._recognize_heuristic(audio)

        return {
            "label": label,
            "confidence": confidence,
            "hype_score": self.EMOTION_HYPE_MAP.get(label, 0.2) * confidence,
            "all_scores": {r["label"]: r["score"] for r in results[:5]},
        }

    def _recognize_heuristic(self, audio: np.ndarray) -> dict:
        """
        Feature-based emotion detection heuristic.

        Key indicators by emotion:
        - Excited/Happy: High pitch variation, high energy, fast speech
        - Angry: High energy, tense voice, sharp attacks
        - Sad: Low energy, slow speech, downward pitch
        - Fearful: High pitch, irregular energy
        - Surprised: Sudden energy spike, high pitch
        - Neutral: Moderate everything
        """
        audio_f = audio.astype(np.float64)

        # Energy features
        rms = float(np.sqrt(np.mean(audio_f ** 2)))
        rms_normalized = min(rms / 5000.0, 1.0)

        # Spectral features
        fft = np.abs(np.fft.rfft(audio_f))
        freqs = np.fft.rfftfreq(len(audio_f), 1.0 / self.sample_rate)

        if np.sum(fft) > 0:
            spectral_centroid = float(np.sum(freqs * fft) / np.sum(fft))
            centroid_norm = min(spectral_centroid / 4000.0, 1.0)
        else:
            centroid_norm = 0.0

        # Zero crossing rate (speech speed indicator)
        signs = np.sign(audio_f)
        zcr = float(np.mean(np.abs(np.diff(signs)) > 0))
        zcr_norm = min(zcr / 0.3, 1.0)

        # Pitch proxy: spectral peak frequency
        peak_idx = np.argmax(fft[:len(fft)//2])
        peak_freq = freqs[peak_idx] if peak_idx < len(freqs) else 0
        # High pitch > 300Hz, Low pitch < 150Hz
        pitch_score = min(peak_freq / 500.0, 1.0) if peak_freq > 0 else 0.0

        # Energy dynamics (attack sharpness)
        if len(audio_f) > 100:
            first_half = np.mean(np.abs(audio_f[:len(audio_f)//2]))
            second_half = np.mean(np.abs(audio_f[len(audio_f)//2:]))
            energy_ratio = first_half / max(second_half, 1e-6)
            attack_score = min(max(energy_ratio - 1, 0), 1.0)
        else:
            attack_score = 0.0

        # Decision heuristics
        scores = {e: 0.1 for e in self.EMOTIONS}

        if rms_normalized > 0.6 and centroid_norm > 0.5 and zcr_norm > 0.4:
            scores["excited"] = 0.7
            scores["happy"] = 0.5
        elif rms_normalized > 0.5 and attack_score > 0.4:
            scores["angry"] = 0.6
        elif rms_normalized < 0.2 and centroid_norm < 0.3:
            scores["sad"] = 0.5
        elif attack_score > 0.6 and pitch_score > 0.5:
            scores["surprised"] = 0.7
            scores["fearful"] = 0.4
        elif pitch_score > 0.7:
            scores["fearful"] = 0.5
        else:
            scores["neutral"] = 0.6

        top_label = max(scores, key=scores.get)

        result = {
            "label": top_label,
            "confidence": scores[top_label],
            "hype_score": self.EMOTION_HYPE_MAP.get(top_label, 0.2) * scores[top_label],
            "features": {
                "rms": round(rms_normalized, 3),
                "centroid": round(centroid_norm, 3),
                "zcr": round(zcr_norm, 3),
                "pitch": round(pitch_score, 3),
                "attack": round(attack_score, 3),
            },
        }
        self._emotion_history.append(result)
        return result

    def get_emotion_trend(self) -> str:
        """Analyze emotion trend over time."""
        if len(self._emotion_history) < 5:
            return "insufficient_data"

        recent = list(self._emotion_history)[-10:]
        labels = [e["label"] for e in recent]
        from collections import Counter
        dominant = Counter(labels).most_common(1)[0][0]
        return dominant

    def get_status(self) -> dict:
        return {
            "model_loaded": self.model is not None,
            "history_size": len(self._emotion_history),
            "trend": self.get_emotion_trend(),
        }


# ---------------------------------------------------------------------------
# Audio Event Classifier
# ---------------------------------------------------------------------------
class AudioEventClassifier:
    """
    Classify specific audio events relevant to gaming streams.

    Event types:
    - scream / yell - high energy, high pitch burst
    - laugh - rhythmic, mid-energy bursts
    - clap - sharp, short, high-frequency impulse
    - gunshot (game) - very sharp attack, high amplitude
    - explosion (game) - sustained high energy, low frequency
    - keyboard_click - rapid short impulses
    - mouse_click - single short impulse
    - cheer / crowd - sustained wide-spectrum energy
    - boo - low frequency sustained energy
    - silence - very low energy
    """

    EVENT_PROFILES = {
        "scream": {
            "min_duration": 0.3, "max_duration": 3.0,
            "min_rms": 0.6, "min_centroid": 0.5,
            "min_zcr": 0.3, "hype_score": 0.9,
        },
        "laugh": {
            "min_duration": 0.2, "max_duration": 2.0,
            "min_rms": 0.3, "min_centroid": 0.4,
            "pattern": "rhythmic", "hype_score": 0.6,
        },
        "clap": {
            "max_duration": 0.15, "min_rms": 0.7,
            "min_centroid": 0.6, "hype_score": 0.5,
        },
        "explosion": {
            "min_duration": 0.1, "max_duration": 3.0,
            "min_rms": 0.8, "max_centroid": 0.3,
            "hype_score": 0.8,
        },
        "crowd_cheer": {
            "min_duration": 1.0, "max_duration": 10.0,
            "min_rms": 0.4, "pattern": "sustained",
            "hype_score": 0.8,
        },
        "crowd_boo": {
            "min_duration": 0.5, "max_duration": 5.0,
            "min_rms": 0.3, "max_centroid": 0.2,
            "hype_score": 0.4,
        },
        "keyboard": {
            "min_rms": 0.2, "pattern": "rapid_impulse",
            "hype_score": 0.1,
        },
    }

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._event_history: deque[dict] = deque(maxlen=100)

    def classify(self, audio: np.ndarray, features: dict) -> list[dict]:
        """
        Classify audio events from chunk features.

        Args:
            audio: Raw audio samples
            features: Pre-extracted features (rms, centroid, zcr, etc.)

        Returns:
            List of detected audio events
        """
        events = []
        audio_f = audio.astype(np.float64)

        # Extract features if not provided
        rms_norm = features.get("rms_energy", 0)
        if not isinstance(rms_norm, (int, float)):
            rms_norm = 0
        rms_norm = min(abs(rms_norm) / 5000.0, 1.0) if abs(rms_norm) > 0 else (
            float(np.sqrt(np.mean(audio_f ** 2))) / 5000.0
        )

        zcr = features.get("zero_crossing_rate", 0)
        if not isinstance(zcr, (int, float)):
            zcr = 0
        if abs(zcr) < 0.001:
            signs = np.sign(audio_f)
            zcr = float(np.mean(np.abs(np.diff(signs)) > 0))

        centroid = features.get("spectral_centroid", 0)
        if not isinstance(centroid, (int, float)):
            centroid = 0
        centroid_norm = min(abs(centroid) / 4000.0, 1.0) if abs(centroid) > 0 else 0.0

        dur = len(audio_f) / self.sample_rate

        # Check each event profile
        for event_name, profile in self.EVENT_PROFILES.items():
            score = 0.0
            matches = 0
            total = 0

            if "min_duration" in profile:
                total += 1
                if profile["min_duration"] <= dur:
                    matches += 1
            if "max_duration" in profile:
                total += 1
                if dur <= profile["max_duration"]:
                    matches += 1

            if "min_rms" in profile:
                total += 1
                if rms_norm >= profile["min_rms"]:
                    matches += 1
                    score += rms_norm * 0.3

            if "min_centroid" in profile:
                total += 1
                if centroid_norm >= profile["min_centroid"]:
                    matches += 1
                    score += centroid_norm * 0.3
            if "max_centroid" in profile:
                total += 1
                if centroid_norm <= profile["max_centroid"]:
                    matches += 1

            if total > 0 and matches / total >= 0.7:
                confidence = matches / total
                events.append({
                    "event": event_name,
                    "confidence": round(confidence, 2),
                    "hype_score": profile.get("hype_score", 0.0) * confidence,
                    "duration": round(dur, 2),
                })

        if events:
            self._event_history.append({
                "timestamp": time.time(),
                "events": events,
            })

        return sorted(events, key=lambda x: x["confidence"], reverse=True)

    def get_status(self) -> dict:
        total = sum(
            len(entry["events"]) for entry in self._event_history
        ) if self._event_history else 0
        return {
            "total_events_detected": total,
            "history_size": len(self._event_history),
        }


# ---------------------------------------------------------------------------
# Crowd Reaction Detector
# ---------------------------------------------------------------------------
class CrowdReactionDetector:
    """
    Detect crowd reactions from audio: cheer, boo, gasp, chant.

    Key indicators:
    - Wide spectral spread (many voices)
    - Sustained energy (not a single spike)
    - Low-mid frequency dominance
    - Rhythmic patterns for chants
    """

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._energy_window: deque[float] = deque(maxlen=30)
        self._reaction_count = 0

    def detect(self, audio_chunk: np.ndarray, features: dict) -> Optional[dict]:
        """
        Detect if this audio chunk contains a crowd reaction.

        Returns dict with reaction type and confidence, or None.
        """
        audio_f = audio_chunk.astype(np.float64)
        rms = float(np.sqrt(np.mean(audio_f ** 2)))
        rms_norm = min(rms / 5000.0, 1.0)
        self._energy_window.append(rms_norm)

        if len(self._energy_window) < 5:
            return None

        # Check for sustained energy (not a brief spike)
        recent = list(self._energy_window)
        avg_energy = float(np.mean(recent))
        energy_std = float(np.std(recent))

        # Crowd reactions have moderate-high energy sustained
        is_sustained = energy_std < 0.2 and avg_energy > 0.3

        # Spectral analysis for "crowd-ness" (wide spectrum, many voices)
        fft = np.abs(np.fft.rfft(audio_f))
        spectral_spread = float(np.std(fft[:len(fft)//2])) / float(np.mean(fft[:len(fft)//2]) + 1e-6)

        if is_sustained and spectral_spread > 1.5:
            reaction_type = "cheer"
            confidence = min(avg_energy * 1.5, 0.9)
        elif avg_energy > 0.5 and spectral_spread > 1.0:
            reaction_type = "cheer"
            confidence = min(avg_energy, 0.8)
        elif avg_energy > 0.25 and spectral_spread < 0.8:
            reaction_type = "boo"
            confidence = min(avg_energy * 1.2, 0.6)
        else:
            return None

        self._reaction_count += 1
        return {
            "reaction_type": reaction_type,
            "confidence": round(confidence, 2),
            "avg_energy": round(avg_energy, 3),
            "duration_sustained": len(recent) / self.sample_rate,
            "spectral_spread": round(spectral_spread, 2),
        }

    def get_status(self) -> dict:
        return {
            "reactions_detected": self._reaction_count,
            "energy_window_size": len(self._energy_window),
        }


# ---------------------------------------------------------------------------
# Music Detector
# ---------------------------------------------------------------------------
class MusicDetector:
    """
    Detect background music in stream audio.

    Music characteristics:
    - Harmonic structure (peaks at musical intervals)
    - Sustained rhythmic pattern
    - Lower speech-to-music ratio
    - Consistent spectral centroid
    """

    GENRE_PROFILES = {
        "electronic": {"centroid_range": (2000, 6000), "rhythm_regularity": 0.7},
        "rock": {"centroid_range": (1000, 4000), "rhythm_regularity": 0.5},
        "ambient": {"centroid_range": (500, 2000), "rhythm_regularity": 0.3},
        "orchestral": {"centroid_range": (500, 3000), "rhythm_regularity": 0.2},
    }

    def __init__(self):
        self._energy_history: deque[float] = deque(maxlen=100)
        self._centroid_history: deque[float] = deque(maxlen=100)
        self._music_confidence = 0.0
        self._detected_genre = None

    def analyze(self, audio_chunk: np.ndarray, features: dict) -> dict:
        """
        Analyze audio chunk for music presence.

        Returns dict with music_present, confidence, genre.
        """
        audio_f = audio_chunk.astype(np.float64)

        # Energy and centroid tracking
        rms = float(np.sqrt(np.mean(audio_f ** 2)))
        self._energy_history.append(rms)

        fft = np.abs(np.fft.rfft(audio_f))
        freqs = np.fft.rfftfreq(len(audio_f), 1.0 / 16000)
        if np.sum(fft) > 0:
            centroid = float(np.sum(freqs * fft) / np.sum(fft))
        else:
            centroid = 0.0
        self._centroid_history.append(centroid)

        if len(self._energy_history) < 10:
            return {"music_present": False, "confidence": 0.0}

        # Music indicators
        energy_recent = list(self._energy_history)[-20:]
        centroid_recent = list(self._centroid_history)[-20:]

        # 1. Energy regularity (music is more regular than speech)
        energy_cv = float(np.std(energy_recent)) / (float(np.mean(energy_recent)) + 1e-6)
        regularity_score = max(0, 1.0 - energy_cv * 2)

        # 2. Centroid stability (music has stable spectral profile)
        centroid_cv = float(np.std(centroid_recent)) / (float(np.mean(centroid_recent)) + 1e-6)
        stability_score = max(0, 1.0 - centroid_cv * 1.5)

        # 3. Harmonic content (check for peaks at musical intervals)
        peak_indices = np.argsort(fft[:len(fft)//2])[-5:]
        peak_freqs = freqs[peak_indices[:5]]
        harmonic_score = 0.0
        if len(peak_freqs) >= 2:
            ratios = [peak_freqs[i] / max(peak_freqs[0], 1) for i in range(1, len(peak_freqs))]
            harmonic_hits = sum(
                1 for r in ratios if any(
                    abs(r - interval) < 0.1
                    for interval in [1.25, 1.33, 1.5, 2.0, 2.5, 3.0, 4.0]
                )
            )
            harmonic_score = harmonic_hits / max(len(ratios), 1)

        # Combined music confidence
        music_score = regularity_score * 0.35 + stability_score * 0.35 + harmonic_score * 0.3
        self._music_confidence = music_score

        # Genre detection
        avg_centroid = float(np.mean(centroid_recent))
        genre = self._detect_genre(avg_centroid, energy_cv)

        return {
            "music_present": music_score > 0.4,
            "confidence": round(music_score, 2),
            "genre": genre if music_score > 0.4 else None,
            "regularity": round(regularity_score, 2),
            "stability": round(stability_score, 2),
            "harmonicity": round(harmonic_score, 2),
            "centroid_avg": round(avg_centroid, 1),
        }

    def _detect_genre(self, centroid: float, energy_cv: float) -> Optional[str]:
        """Detect music genre from centroid and rhythm."""
        best_genre = None
        best_score = 0.0
        for genre_name, profile in self.GENRE_PROFILES.items():
            low, high = profile["centroid_range"]
            rhythm_match = profile["rhythm_regularity"]
            centroid_score = 1.0 if low <= centroid <= high else (
                0.5 if abs(centroid - (low + high) / 2) < 1000 else 0.0
            )
            rhythm_score = 1.0 - abs((1.0 - energy_cv * 2) - rhythm_match)
            total = centroid_score * 0.6 + rhythm_score * 0.4
            if total > best_score:
                best_score = total
                best_genre = genre_name
        return best_genre if best_score > 0.5 else None

    def get_status(self) -> dict:
        return {
            "music_detected": self._music_confidence > 0.4,
            "confidence": round(self._music_confidence, 2),
            "current_genre": self._detected_genre,
        }