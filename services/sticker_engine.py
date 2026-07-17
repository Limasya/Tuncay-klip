"""
Sticker/emoji overlay motoru.
Dinamik sticker yerleştirme, emoji animasyonları, reaksiyon efektleri.
"""
import logging
import math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class StickerDef:
    """Sticker tanımı."""
    emoji: str
    x: float = 0.5       # 0-1 arası oran (0.5 = orta)
    y: float = 0.5
    start: float = 0.0
    duration: float = 2.0
    scale: float = 1.0
    animation: str = "pop"    # pop, float, spin, bounce, shake
    opacity: float = 1.0


# Emoji→FFmpeg drawtext mapping (desteklenen emojiler)
EMOJI_MAP = {
    "fire": "\\U0001F525",
    "heart": "\\u2764\\uFE0F",
    "star": "\\u2B50",
    "clap": "\\U0001F44F",
    "laugh": "\\U0001F602",
    "cry": "\\U0001F602",
    "angry": "\\U0001F621",
    "cool": "\\U0001F60E",
    "rocket": "\\U0001F680",
    "check": "\\u2705",
    "cross": "\\u274C",
    "warning": "\\u26A0\\uFE0F",
    "thumbsup": "\\U0001F44D",
    "100": "\\U0001F4AF",
    "money": "\\U0001F4B0",
    "crown": "\\U0001F451",
    "lightning": "\\u26A1",
    "sparkles": "\\u2728",
    "boom": "\\U0001F4A5",
    "muscle": "\\U0001F4AA",
    "trophy": "\\U0001F3C6",
    "medal": "\\U0001F3C5",
    "soccer": "\\u26BD",
    "gun": "\\U0001F52B",
    "skull": "\\U0001F480",
    "tada": "\\U0001F389",
}


class StickerEngine:
    """
    Sticker/emoji overlay motoru.
    FFmpeg drawtext ile emoji/overlay üretir.
    """

    def __init__(self):
        self._emojis = dict(EMOJI_MAP)

    def generate_sticker_filter(
        self,
        stickers: List[StickerDef],
        video_width: int = 1080,
        video_height: int = 1920,
    ) -> str:
        """
        Sticker listesinden FFmpeg filter string'i üretir.
        """
        if not stickers:
            return "null"

        filters = []
        for s in stickers:
            # Konumu piksel cinsine çevir
            px_x = int(s.x * video_width)
            px_y = int(s.y * video_height)

            # Emoji drawtext
            emoji_char = self._emojis.get(s.emoji, s.emoji)

            # Animasyon efekti
            if s.animation == "pop":
                # Pop: ölçek animasyonu
                filters.append(
                    f"drawtext=text='{emoji_char}':"
                    f"fontsize={int(64 * s.scale)}:"
                    f"fontcolor=white@{s.opacity:.2f}:"
                    f"x={px_x}:y={px_y}:"
                    f"enable='between(t,{s.start:.2f},{s.start + s.duration:.2f})'"
                )
            elif s.animation == "float":
                # Float: yukarı doğru süzülme
                filters.append(
                    f"drawtext=text='{emoji_char}':"
                    f"fontsize={int(64 * s.scale)}:"
                    f"fontcolor=white@{s.opacity:.2f}:"
                    f"x={px_x}:y={px_y}-t*20:"
                    f"enable='between(t,{s.start:.2f},{s.start + s.duration:.2f})'"
                )
            elif s.animation == "bounce":
                # Bounce: zıplama
                filters.append(
                    f"drawtext=text='{emoji_char}':"
                    f"fontsize={int(64 * s.scale)}:"
                    f"fontcolor=white@{s.opacity:.2f}:"
                    f"x={px_x}:y={px_y}-abs(sin(t*5)*30):"
                    f"enable='between(t,{s.start:.2f},{s.start + s.duration:.2f})'"
                )
            elif s.animation == "spin":
                # Spin: döndürme (basitleştirilmiş)
                filters.append(
                    f"drawtext=text='{emoji_char}':"
                    f"fontsize={int(64 * s.scale)}:"
                    f"fontcolor=white@{s.opacity:.2f}:"
                    f"x={px_x}:y={px_y}:"
                    f"enable='between(t,{s.start:.2f},{s.start + s.duration:.2f})'"
                )
            elif s.animation == "shake":
                # Shake: sarsılma
                filters.append(
                    f"drawtext=text='{emoji_char}':"
                    f"fontsize={int(64 * s.scale)}:"
                    f"fontcolor=white@{s.opacity:.2f}:"
                    f"x={px_x}+sin(t*20)*5:y={px_y}:"
                    f"enable='between(t,{s.start:.2f},{s.start + s.duration:.2f})'"
                )
            else:
                # Statik
                filters.append(
                    f"drawtext=text='{emoji_char}':"
                    f"fontsize={int(64 * s.scale)}:"
                    f"fontcolor=white@{s.opacity:.2f}:"
                    f"x={px_x}:y={px_y}:"
                    f"enable='between(t,{s.start:.2f},{s.start + s.duration:.2f})'"
                )

        return ",".join(filters)

    def generate_reaction_overlay(
        self,
        reaction_type: str,
        start_time: float,
        duration: float = 2.0,
        intensity: float = 1.0,
    ) -> str:
        """
        Reaksiyon overlay'i üretir.

        reaction_type: "fire", "hype", "fail", "victory", "love", "shock"
        """
        # Reaksiyon tipine göre sticker seti
        reaction_stickers = {
            "fire": [
                StickerDef("fire", 0.3, 0.3, start_time, duration, intensity),
                StickerDef("fire", 0.7, 0.4, start_time + 0.3, duration, intensity * 0.8),
                StickerDef("fire", 0.5, 0.2, start_time + 0.6, duration, intensity * 0.6),
            ],
            "hype": [
                StickerDef("rocket", 0.5, 0.3, start_time, duration, intensity * 1.2),
                StickerDef("star", 0.3, 0.5, start_time + 0.2, duration * 0.8, intensity),
                StickerDef("star", 0.7, 0.5, start_time + 0.4, duration * 0.8, intensity),
                StickerDef("100", 0.5, 0.7, start_time + 0.6, duration * 0.6, intensity),
            ],
            "fail": [
                StickerDef("cross", 0.5, 0.5, start_time, duration, intensity * 1.5),
                StickerDef("warning", 0.5, 0.3, start_time + 0.5, duration * 0.5, intensity),
            ],
            "victory": [
                StickerDef("crown", 0.5, 0.2, start_time, duration, intensity * 1.3),
                StickerDef("trophy", 0.5, 0.5, start_time + 0.3, duration * 0.8, intensity),
                StickerDef("sparkles", 0.3, 0.4, start_time + 0.5, duration * 0.6, intensity),
                StickerDef("sparkles", 0.7, 0.4, start_time + 0.7, duration * 0.6, intensity),
            ],
            "love": [
                StickerDef("heart", 0.5, 0.5, start_time, duration, intensity * 1.5),
                StickerDef("heart", 0.3, 0.3, start_time + 0.3, duration * 0.7, intensity),
                StickerDef("heart", 0.7, 0.3, start_time + 0.5, duration * 0.7, intensity),
            ],
            "shock": [
                StickerDef("boom", 0.5, 0.5, start_time, duration, intensity * 2),
                StickerDef("lightning", 0.3, 0.3, start_time + 0.2, duration * 0.5, intensity),
                StickerDef("lightning", 0.7, 0.3, start_time + 0.4, duration * 0.5, intensity),
            ],
        }

        stickers = reaction_stickers.get(reaction_type, reaction_stickers["fire"])
        return self.generate_sticker_filter(stickers)

    def generate_emoji_rain(
        self,
        emoji: str,
        start_time: float,
        duration: float = 3.0,
        count: int = 20,
        video_width: int = 1080,
        video_height: int = 1920,
    ) -> str:
        """
        Emoji yağmuru efekti üretir.
        Ekranın üstünden düşen emoji'ler.
        """
        filters = []
        emoji_char = self._emojis.get(emoji, emoji)

        for i in range(count):
            # Rastgele konum ve zaman
            x = (i * 37 + 13) % video_width  # Pseudo-random x
            start_offset = (i * 0.15) % duration
            fall_speed = 100 + (i * 23) % 100  # Farklı hızlar

            filters.append(
                f"drawtext=text='{emoji_char}':"
                f"fontsize={32 + (i % 3) * 8}:"
                f"fontcolor=white@{0.6 + (i % 4) * 0.1:.2f}:"
                f"x={x}:y=-50+t*{fall_speed}:"
                f"enable='between(t,{start_time + start_offset:.2f},"
                f"{start_time + duration:.2f})'"
            )

        return ",".join(filters)

    def generate_confetti(
        self,
        start_time: float,
        duration: float = 3.0,
        count: int = 30,
        colors: List[str] = None,
    ) -> str:
        """
        Konfeti efekti üretir.
        Renkli kareler yağmuru.
        """
        if colors is None:
            colors = ["red", "yellow", "blue", "green", "magenta", "cyan"]

        filters = []
        for i in range(count):
            color = colors[i % len(colors)]
            x = (i * 43 + 17) % 1080
            y_speed = 80 + (i * 31) % 120
            size = 4 + (i % 5) * 2
            start_offset = (i * 0.1) % (duration * 0.5)

            filters.append(
                f"drawbox=x={x}:y=-{size}-t*{y_speed}:"
                f"w={size}:h={size}:"
                f"color={color}@0.8:t=fill:"
                f"enable='between(t,{start_time + start_offset:.2f},"
                f"{start_time + duration:.2f})'"
            )

        return ",".join(filters)

    def get_available_emojis(self) -> List[str]:
        """Mevcut emoji isimlerini döndürür."""
        return list(self._emojis.keys())


# Singleton
sticker_engine = StickerEngine()
