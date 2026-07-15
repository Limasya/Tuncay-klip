"""
Müzik ve ses efekti servisi.
Otomatik müzik seçimi, ses analizi, ducking, SFX kütüphane yönetimi.
"""
import asyncio
import json
import logging
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MUSIC_DIR = Path("data/music")
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

SFX_DIR = Path("data/sfx")
SFX_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class MusicTrack:
    """Müzik parçası metadata."""
    path: str
    genre: str
    mood: str
    bpm: int
    duration: float
    energy_level: str  # low, medium, high
    tags: List[str]


@dataclass
class SFXClip:
    """Ses efekti metadata."""
    path: str
    category: str
    duration: float
    tags: List[str]


# Mood → müzik eşleme
MOOD_MUSIC_MAP = {
    "happy": ["upbeat", "cheerful", "energetic"],
    "excited": ["high_energy", "electronic", "intense"],
    "angry": ["dark", "aggressive", "heavy"],
    "sad": ["melancholic", "piano", "ambient"],
    "surprise": ["dramatic", "suspense", "cinematic"],
    "fear": ["horror", "tension", "dark_ambient"],
    "neutral": ["chill", "lofi", "background"],
    "wholesome": ["warm", "acoustic", "gentle"],
}

# Kategori → müzik enerji seviyesi
CATEGORY_ENERGY = {
    "exciting": "high",
    "funny": "medium",
    "emotional": "low",
    "rage": "high",
    "wholesome": "low",
    "skill": "high",
    "fail": "medium",
    "victory": "high",
}

# SFX kategorileri
SFX_CATEGORIES = {
    "impact": ["hit", "punch", "slam", "boom"],
    "transition": ["whoosh", "swoosh", "swipe"],
    "emotion": ["laugh", "gasp", "scream", "applause"],
    "game": ["victory", "defeat", "level_up", "combo"],
    "notification": ["ding", "bell", "alert", "pop"],
}


class MusicService:
    """
    Müzik ve ses efekti yönetimi servisi.
    """

    def __init__(self):
        self._music_library: List[MusicTrack] = []
        self._sfx_library: List[SFXClip] = []
        self._scan_library()

    def _scan_library(self):
        """Müzik ve SFX kütüphanelerini tarar."""
        # Müzik taraması
        for ext in ("*.mp3", "*.wav", "*.ogg", "*.m4a"):
            for f in MUSIC_DIR.rglob(ext):
                self._music_library.append(MusicTrack(
                    path=str(f),
                    genre="unknown",
                    mood="neutral",
                    bpm=120,
                    duration=0,
                    energy_level="medium",
                    tags=[f.stem.lower()],
                ))

        # SFX taraması
        for ext in ("*.mp3", "*.wav", "*.ogg"):
            for f in SFX_DIR.rglob(ext):
                self._sfx_library.append(SFXClip(
                    path=str(f),
                    category="unknown",
                    duration=0,
                    tags=[f.stem.lower()],
                ))

        logger.info(
            "Kütüphane tarandı: %d müzik, %d SFX",
            len(self._music_library), len(self._sfx_library),
        )

    def select_music_for_clip(
        self,
        emotion: str,
        category: str,
        duration: float,
        exclude_paths: Optional[List[str]] = None,
    ) -> Optional[MusicTrack]:
        """
        Klip için en uygun müziği seçer.

        Args:
            emotion: Dominant duygu
            category: Klip kategorisi
            duration: Klip süresi (saniye)
            exclude_paths: Hariç tutulacak müzik yolları
        """
        if not self._music_library:
            logger.warning("Müzik kütüphane boş")
            return None

        desired_moods = MOOD_MUSIC_MAP.get(emotion, ["chill", "background"])
        desired_energy = CATEGORY_ENERGY.get(category, "medium")
        exclude = set(exclude_paths or [])

        candidates = []
        for track in self._music_library:
            if track.path in exclude:
                continue

            score = 0
            # Mood eşleşmesi
            if any(m in track.tags for m in desired_moods):
                score += 3
            # Enerji eşleşmesi
            if track.energy_level == desired_energy:
                score += 2
            # Süre uygunluğu (klibin en az %80'i kadar olmalı)
            if track.duration >= duration * 0.8:
                score += 1

            candidates.append((score, track))

        if not candidates:
            return random.choice(self._music_library)

        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def select_sfx_for_event(
        self,
        event_type: str,
        emotion: str,
        audio_energy: str,
    ) -> Optional[SFXClip]:
        """
        Bir olay için ses efekti seçer.
        """
        if not self._sfx_library:
            return None

        # Olay tipine göre SFX kategorisi belirle
        sfx_category = self._map_event_to_sfx(event_type, emotion)

        candidates = [
            sfx for sfx in self._sfx_library
            if sfx.category == sfx_category or sfx_category in sfx.tags
        ]

        if not candidates:
            # Herhangi bir SFX dön
            return random.choice(self._sfx_library)

        return random.choice(candidates)

    def calculate_ducking_params(
        self,
        speech_level: float,
        music_level: float,
        target_ratio: float = 0.15,
    ) -> Dict:
        """
        Speech-music ducking parametrelerini hesaplar.

        Args:
            speech_level: Konuşma ses seviyesi (0-1)
            music_level: Müzik ses seviyesi (0-1)
            target_ratio: Hedef music/speech oranı
        """
        if speech_level <= 0:
            return {
                "threshold": 0.01,
                "ratio": 1,
                "attack": 500,
                "release": 1000,
            }

        # Sidechaincompress parametreleri
        threshold = speech_level * 0.5
        ratio = max(2, min(20, speech_level / (target_ratio * music_level + 0.001)))
        attack = 200 if speech_level > 0.5 else 500
        release = 800 if speech_level > 0.5 else 1500

        return {
            "threshold": threshold,
            "ratio": ratio,
            "attack": attack,
            "release": release,
        }

    def build_ducking_filter(
        self,
        music_volume: float,
        duck_params: Dict,
    ) -> str:
        """
        FFmpeg ducking filter string'i oluşturur.
        """
        return (
            f"sidechaincompress=threshold={duck_params['threshold']:.4f}:"
            f"ratio={duck_params['ratio']:.1f}:"
            f"attack={int(duck_params['attack'])}:"
            f"release={int(duck_params['release'])}"
        )

    def analyze_audio_for_music_selection(
        self, audio_features: Dict
    ) -> Dict:
        """
        Ses özelliklerinden müzik seçim bilgileri üretir.
        """
        rms = audio_features.get("rms_energy", 0.0)
        zcr = audio_features.get("zero_crossing_rate", 0.0)
        spectral_centroid = audio_features.get("spectral_centroid", 0.0)

        # Enerji seviyesi
        if rms > 0.1:
            energy = "high"
        elif rms > 0.03:
            energy = "medium"
        else:
            energy = "low"

        # Tempo tahmini (ZCR'den rough estimate)
        estimated_bpm = max(60, min(200, int(zcr * 300 + 80)))

        # Frekans profili
        if spectral_centroid > 3000:
            brightness = "bright"
        elif spectral_centroid > 1500:
            brightness = "medium"
        else:
            brightness = "dark"

        return {
            "energy_level": energy,
            "estimated_bpm": estimated_bpm,
            "brightness": brightness,
            "music_volume_suggestion": 0.3 if energy == "high" else 0.4,
        }

    def get_available_music(self) -> List[Dict]:
        """Mevcut müzik kütüphanesini döndürür."""
        return [
            {
                "path": t.path,
                "genre": t.genre,
                "mood": t.mood,
                "bpm": t.bpm,
                "energy": t.energy_level,
                "tags": t.tags,
            }
            for t in self._music_library
        ]

    def get_available_sfx(self) -> List[Dict]:
        """Mevcut SFX kütüphanesini döndürür."""
        return [
            {
                "path": s.path,
                "category": s.category,
                "tags": s.tags,
            }
            for s in self._sfx_library
        ]

    def _map_event_to_sfx(self, event_type: str, emotion: str) -> str:
        """Olay tipi ve duygu SFX kategorisine eşler."""
        event_sfx_map = {
            "clip_trigger": "impact",
            "scene_change": "transition",
            "high_score": "game",
            "chat_spike": "notification",
            "emotion_peak": "emotion",
        }
        return event_sfx_map.get(event_type, "impact")


# Singleton
music_service = MusicService()
