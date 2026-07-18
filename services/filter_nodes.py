"""
FFmpeg Filter Nodes — Modular Filter Building Blocks
─────────────────────────────────────────────────────
Her filtre küçük, bağımsız bir node'dur.
Yeni efekt eklemek = yeni bir node yazmak kadar kolay.

Akış:
  FilterNode → build() → FFmpeg filter string
  FilterChain → add(node) → combine() → full filter string
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class FilterNode(ABC):
    """Tüm filtre node'larının soyut temeli."""
    name: str = ""
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)

    @abstractmethod
    def build(self) -> str:
        """FFmpeg filter string'i üret."""
        ...

    @property
    def is_active(self) -> bool:
        return self.enabled and bool(self.build().strip())


class FilterChain:
    """Filtreleri birleştirip tam bir zincir oluşturur."""

    def __init__(self):
        self._nodes: list[FilterNode] = []

    def add(self, node: FilterNode) -> FilterChain:
        """Node ekle (fluent API)."""
        if node.is_active:
            self._nodes.append(node)
        return self

    def add_conditional(self, condition: bool, node: FilterNode) -> FilterChain:
        """Koşullu node ekle."""
        if condition and node.is_active:
            self._nodes.append(node)
        return self

    def build_video(self) -> str:
        """Tüm video filtrelerini birleştir."""
        filters = [n.build() for n in self._nodes if isinstance(n, VideoFilterNode)]
        return ",".join(f for f in filters if f)

    def build_audio(self) -> str:
        """Tüm audio filtrelerini birleştir."""
        filters = [n.build() for n in self._nodes if isinstance(n, AudioFilterNode)]
        return ",".join(f for f in filters if f)

    def build_complex(self) -> str:
        """Complex filter graph için tüm filtreleri birleştir."""
        video = self.build_video()
        audio = self.build_audio()
        parts = []
        if video:
            parts.append(f"-vf '{video}'")
        if audio:
            parts.append(f"-af '{audio}'")
        return " ".join(parts)

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def node_names(self) -> list[str]:
        return [n.name for n in self._nodes]


class VideoFilterNode(FilterNode):
    """Video filtreleri için temel."""
    pass


class AudioFilterNode(FilterNode):
    """Audio filtreleri için temel."""
    pass


# ═══════════════════════════════════════════════════════════════
# VIDEO FILTER NODES
# ═══════════════════════════════════════════════════════════════

class ScaleNode(VideoFilterNode):
    """Video ölçekleme + aspect ratio."""

    def __init__(self, width: int = 1080, height: int = 1920,
                 aspect_ratio: str = "9:16", pad_color: str = "black"):
        super().__init__(name="scale")
        self.width = width
        self.height = height
        self.aspect_ratio = aspect_ratio
        self.pad_color = pad_color

    def build(self) -> str:
        if self.aspect_ratio == "9:16":
            return (f"crop=ih*9/16:ih,scale={self.width}:{self.height}"
                    f":force_original_aspect_ratio=decrease"
                    f",pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:{self.pad_color}")
        elif self.aspect_ratio == "16:9":
            return (f"scale={self.width}:{self.height}"
                    f":force_original_aspect_ratio=decrease"
                    f",pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:{self.pad_color}")
        elif self.aspect_ratio == "1:1":
            return f"crop='min(iw,ih)':'min(iw,ih)',scale={self.width}:{self.height}"
        elif self.aspect_ratio == "4:5":
            return (f"crop=ih*4/5:ih,scale={self.width}:{self.height}"
                    f":force_original_aspect_ratio=decrease"
                    f",pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:{self.pad_color}")
        return f"scale={self.width}:{self.height}"


class ColorGradingNode(VideoFilterNode):
    """Renk ayarlama (brightness, contrast, saturation, gamma) ve sinematik LUT/Curves."""

    PRESETS = {
        "vibrant": {"brightness": 0.02, "contrast": 1.1, "saturation": 1.3, "gamma": 1.0},
        "warm": {"brightness": 0.03, "contrast": 1.05, "saturation": 1.1, "gamma": 1.0},
        "cool": {"brightness": -0.02, "contrast": 1.05, "saturation": 0.9, "gamma": 1.0},
        "cinematic": {"brightness": -0.05, "contrast": 1.2, "saturation": 0.85, "gamma": 0.95},
        "vintage": {"brightness": 0.02, "contrast": 1.1, "saturation": 0.7, "gamma": 1.1},
        "high_contrast": {"brightness": -0.03, "contrast": 1.4, "saturation": 0.9, "gamma": 1.0},
        "desaturated": {"brightness": 0.0, "contrast": 1.1, "saturation": 0.4, "gamma": 1.0},
        "premium_dark": {"brightness": -0.04, "contrast": 1.25, "saturation": 1.15, "gamma": 0.9},
    }

    def __init__(self, preset: str = "", brightness: float = 0.0,
                 contrast: float = 1.0, saturation: float = 1.0, gamma: float = 1.0,
                 lut_path: str = ""):
        super().__init__(name="color_grading")
        self.lut_path = lut_path
        if preset and preset in self.PRESETS:
            p = self.PRESETS[preset]
            self.brightness = p["brightness"]
            self.contrast = p["contrast"]
            self.saturation = p["saturation"]
            self.gamma = p["gamma"]
        else:
            self.brightness = brightness
            self.contrast = contrast
            self.saturation = saturation
            self.gamma = gamma

    def build(self) -> str:
        if self.lut_path:
            return f"lut3d=file='{self.lut_path}'"
            
        return (f"eq=brightness={self.brightness}:contrast={self.contrast}"
                f":saturation={self.saturation}:gamma={self.gamma}")


class MotionBlurNode(VideoFilterNode):
    """
    Hızlı sahnelerde sinematik akıcılık sağlayan hareket bulanıklığı.
    'tmix' filtresini kullanarak birbirini takip eden kareleri harmanlar.
    """
    def __init__(self, frames: int = 3):
        super().__init__(name="motion_blur")
        self.frames = frames

    def build(self) -> str:
        if self.frames <= 1:
            return ""
        # tmix: frameleri birbirine karistirarak motion blur hissi yaratir
        return f"tmix=frames={self.frames}:weights=\"1\""


class FrostedGlassNode(VideoFilterNode):
    """
    Videoyu arkaya alıp bulanıklaştıran ve üzerini karartan premium glassmorphism arka plan.
    (Genelde split-screen veya padding işlemleri için complex filtergraph içinde kullanılır).
    Bu node sadece videoyu blurlayıp karartır.
    """
    def __init__(self, blur_radius: int = 40, darken_amount: float = 0.6):
        super().__init__(name="frosted_glass")
        self.blur_radius = blur_radius
        self.darken_amount = darken_amount

    def build(self) -> str:
        # boxblur veya gblur ile yuksek bulaniklik, eq ile karartma
        return f"boxblur={self.blur_radius}:5,eq=brightness=-{self.darken_amount}"


class VignetteNode(VideoFilterNode):
    """Vignette efekti."""

    def __init__(self, intensity: float = 0.5):
        super().__init__(name="vignette")
        self.intensity = intensity

    def build(self) -> str:
        angle = 4.0 - self.intensity * 2.0
        return f"vignette=PI/{angle:.2f}"


class GlowNode(VideoFilterNode):
    """Unsharp glow efekti."""

    def __init__(self, intensity: float = 0.5):
        super().__init__(name="glow")
        self.intensity = intensity

    def build(self) -> str:
        amount = self.intensity * 2
        return f"unsharp=3:3:{amount}:3:3:0"


class SharpenNode(VideoFilterNode):
    """Unsharp sharpen efekti."""

    def __init__(self, intensity: float = 0.5):
        super().__init__(name="sharpen")
        self.intensity = intensity

    def build(self) -> str:
        return f"unsharp=5:5:{self.intensity * 5}:5:5:0"


class FilmGrainNode(VideoFilterNode):
    """Film grain noise efekti."""

    def __init__(self, intensity: float = 0.3):
        super().__init__(name="film_grain")
        self.intensity = intensity

    def build(self) -> str:
        amount = int(self.intensity * 50)
        return f"noise=alls={amount}:allf=t"


class ChromaticAberrationNode(VideoFilterNode):
    """Chromatic aberration efekti."""

    def __init__(self, intensity: float = 0.3):
        super().__init__(name="chromatic_aberration")
        self.intensity = intensity

    def build(self) -> str:
        offset = int(self.intensity * 5)
        return f"rgbashift=rh={offset}:bh=-{offset}"


class CameraShakeNode(VideoFilterNode):
    """Kamera sallanma efekti (statik)."""

    def __init__(self, amplitude: int = 8):
        super().__init__(name="camera_shake")
        self.amplitude = amplitude

    def build(self) -> str:
        a = self.amplitude
        return (f"crop=iw-{a*2}:ih-{a*2}:{a}+random(1)*{a}:{a}+random(2)*{a}"
                f",scale=iw+{a*2}:ih+{a*2}")


class SpeedNode(VideoFilterNode):
    """Video hız ayarı (setpts)."""

    def __init__(self, speed: float = 1.0):
        super().__init__(name="speed")
        self.speed = speed

    def build(self) -> str:
        if self.speed == 1.0:
            return ""
        return f"setpts={1.0/self.speed:.4f}*PTS"


class ZoomNode(VideoFilterNode):
    """Zoom efekti (zoompan)."""

    def __init__(self, level: float = 1.5, duration: float = 2.0, fps: int = 25):
        super().__init__(name="zoom")
        self.level = level
        self.duration = duration
        self.fps = fps

    def build(self) -> str:
        frames = int(self.duration * self.fps)
        return (f"zoompan=z='min({self.level},{self.level}*on/({self.duration}*{self.fps}))'"
                f":x='iw/2-iw/(2*z)':y='ih/2-ih/(2*z)'"
                f":d={frames}:s=1080x1920:fps={self.fps}")


class KenBurnsNode(VideoFilterNode):
    """Ken Burns (pan + zoom) efekti."""

    def __init__(self, z_start: float = 1.0, z_end: float = 1.5,
                 pan_x: str = "iw/2-iw/(2*z)", pan_y: str = "ih/2-ih/(2*z)",
                 duration: float = 3.0, fps: int = 25):
        super().__init__(name="ken_burns")
        self.z_start = z_start
        self.z_end = z_end
        self.pan_x = pan_x
        self.pan_y = pan_y
        self.duration = duration
        self.fps = fps

    def build(self) -> str:
        frames = int(self.duration * self.fps)
        return (f"zoompan=z='{self.z_start}+({self.z_end}-{self.z_start})*on/{frames}'"
                f":x='{self.pan_x}':y='{self.pan_y}'"
                f":d={frames}:s=1080x1920:fps={self.fps}")


class WatermarkNode(VideoFilterNode):
    """Metin filigran (drawtext)."""

    def __init__(self, text: str, font_size: int = 20, color: str = "white",
                 opacity: float = 0.7, position: str = "bottom_right"):
        super().__init__(name="watermark")
        self.text = text
        self.font_size = font_size
        self.color = color
        self.opacity = opacity
        self.position = position

    def build(self) -> str:
        pos_map = {
            "bottom_right": "w-tw-20:y=h-th-20",
            "bottom_left": "x=20:y=h-th-20",
            "top_right": "x=w-tw-20:y=20",
            "top_left": "x=20:y=20",
            "center": "x=(w-tw)/2:y=(h-th)/2",
        }
        pos = pos_map.get(self.position, pos_map["bottom_right"])
        escaped = self.text.replace("'", "\\'").replace(":", "\\:")
        return (f"drawtext=text='{escaped}':fontsize={self.font_size}"
                f":fontcolor={self.color}@{self.opacity}"
                f":borderw=1:bordercolor=black@0.50:{pos}")


class TransitionNode(VideoFilterNode):
    """Xfade geçiş efekti (2 klip arası)."""

    TYPES = {
        "fade": "fade", "dissolve": "dissolve", "wipe_left": "wipeleft",
        "wipe_right": "wiperight", "slide_left": "slideleft",
        "slide_right": "slideright", "fade_black": "fadeblack",
        "fade_white": "fadewhite", "radial": "radial",
        "circlecrop": "circlecrop",
    }

    def __init__(self, transition_type: str = "fade", duration: float = 0.5):
        super().__init__(name="transition")
        self.transition_type = transition_type
        self.duration = duration

    def build(self) -> str:
        xfade_type = self.TYPES.get(self.transition_type, self.transition_type)
        return f"xfade=transition={xfade_type}:duration={self.duration}"


# ═══════════════════════════════════════════════════════════════
# AUDIO FILTER NODES
# ═══════════════════════════════════════════════════════════════

class VolumeNode(AudioFilterNode):
    """Ses seviyesi ayarı."""

    def __init__(self, volume: float = 1.0):
        super().__init__(name="volume")
        self.volume = volume

    def build(self) -> str:
        if self.volume == 1.0:
            return ""
        return f"volume={self.volume}"


class AtempoNode(AudioFilterNode):
    """Audio hız ayarı."""

    def __init__(self, speed: float = 1.0):
        super().__init__(name="atempo")
        self.speed = speed

    def build(self) -> str:
        if self.speed == 1.0:
            return ""
        return f"atempo={self.speed}"


class DuckingNode(AudioFilterNode):
    """Speech-music ducking (sidechain compress)."""

    def __init__(self, threshold: float = 0.02, ratio: int = 4):
        super().__init__(name="ducking")
        self.threshold = threshold
        self.ratio = ratio

    def build(self) -> str:
        return (f"sidechaincompress=threshold={self.threshold}"
                f":ratio={self.ratio}:attack=200:release=1000")


class FadeNode(AudioFilterNode):
    """Audio fade in/out."""

    def __init__(self, fade_in: float = 0.0, fade_out: float = 0.0):
        super().__init__(name="fade")
        self.fade_in = fade_in
        self.fade_out = fade_out

    def build(self) -> str:
        parts = []
        if self.fade_in > 0:
            parts.append(f"afade=t=in:d={self.fade_in}")
        if self.fade_out > 0:
            parts.append(f"afade=t=out:st=9999:d={self.fade_out}")
        return ",".join(parts)


# ═══════════════════════════════════════════════════════════════
# COMPOSITE NODES (Çoklu filtre birleştirme)
# ═══════════════════════════════════════════════════════════════

class BeatSyncNode(VideoFilterNode):
    """Beat senkronize zoom + flash + shake."""

    def __init__(self, bpm: float = 120, zoom_amp: float = 0.1,
                 flash_intensity: float = 0.3, fps: int = 25):
        super().__init__(name="beat_sync")
        self.bpm = bpm
        self.zoom_amp = zoom_amp
        self.flash_intensity = flash_intensity
        self.fps = fps

    def build(self) -> str:
        fpb = int(60 / self.bpm * self.fps)
        zoom = (f"zoompan=z='1+{self.zoom_amp}*sin(2*PI*on/{fpb})'"
                f":x='iw/2-iw/(2*z)':y='ih/2-ih/(2*z)':d=1:s=1080x1920:fps={self.fps}")
        flash = (f"eq=brightness={self.flash_intensity}*sin(2*PI*on/{fpb})"
                f":saturation=1+{self.flash_intensity*0.1}*sin(2*PI*on/{fpb})")
        return f"{zoom},{flash}"


class EmotionArcNode(VideoFilterNode):
    """Duygu bazlı renk + hız + vignette."""

    EMOTIONS = {
        "happy": {"saturation": 1.2, "contrast": 1.05, "brightness": 0.02, "vignette": 0.0, "speed": 1.0},
        "excited": {"saturation": 1.4, "contrast": 1.1, "brightness": 0.03, "vignette": 0.1, "speed": 1.2},
        "angry": {"saturation": 0.9, "contrast": 1.3, "brightness": -0.03, "vignette": 0.3, "speed": 1.0},
        "sad": {"saturation": 0.7, "contrast": 0.95, "brightness": -0.05, "vignette": 0.2, "speed": 0.8},
        "fear": {"saturation": 0.6, "contrast": 1.2, "brightness": -0.08, "vignette": 0.4, "speed": 0.9},
        "surprise": {"saturation": 1.1, "contrast": 1.1, "brightness": 0.02, "vignette": 0.1, "speed": 1.1},
        "neutral": {"saturation": 1.0, "contrast": 1.0, "brightness": 0.0, "vignette": 0.0, "speed": 1.0},
        "disgust": {"saturation": 0.5, "contrast": 1.15, "brightness": -0.04, "vignette": 0.3, "speed": 0.9},
    }

    def __init__(self, emotion: str = "neutral"):
        super().__init__(name="emotion_arc")
        self.emotion = emotion
        self._params = self.EMOTIONS.get(emotion, self.EMOTIONS["neutral"])

    def build(self) -> str:
        parts = []
        parts.append(f"eq=brightness={self._params['brightness']}"
                    f":contrast={self._params['contrast']}"
                    f":saturation={self._params['saturation']}")
        if self._params["vignette"] > 0:
            angle = 4.0 - self._params["vignette"] * 2.0
            parts.append(f"vignette=PI/{angle:.2f}")
        if self._params["speed"] != 1.0:
            parts.append(f"setpts={1.0/self._params['speed']:.4f}*PTS")
        return ",".join(parts)


class StickerNode(VideoFilterNode):
    """Emoji/sticker overlay (drawtext + enable)."""

    def __init__(self, emoji: str, x: int = 100, y: int = 100,
                 start: float = 0, end: float = 5, scale: float = 1.0,
                 animation: str = "static"):
        super().__init__(name="sticker")
        self.emoji = emoji
        self.x = x
        self.y = y
        self.start = start
        self.end = end
        self.scale = scale
        self.animation = animation

    def build(self) -> str:
        fs = int(64 * self.scale)
        enable = f"enable='between(t,{self.start},{self.end})'"

        if self.animation == "float":
            return (f"drawtext=text='{self.emoji}':fontsize={fs}"
                    f":fontcolor=white@0.8:x={self.x}:y={self.y}-t*20:{enable}")
        elif self.animation == "bounce":
            return (f"drawtext=text='{self.emoji}':fontsize={fs}"
                    f":fontcolor=white@0.8:x={self.x}:y={self.y}-abs(sin(t*5)*30):{enable}")
        elif self.animation == "shake":
            return (f"drawtext=text='{self.emoji}':fontsize={fs}"
                    f":fontcolor=white@0.8:x={self.x}+sin(t*20)*5:y={self.y}:{enable}")
        else:
            return (f"drawtext=text='{self.emoji}':fontsize={fs}"
                    f":fontcolor=white@0.8:x={self.x}:y={self.y}:{enable}")


class LowerThirdNode(VideoFilterNode):
    """Alt üçte metin overlay."""

    def __init__(self, name: str, title: str = "", style: str = "modern",
                 start: float = 0, end: float = 5):
        super().__init__(name="lower_third")
        self.name_text = name
        self.title = title
        self.style = style
        self.start = start
        self.end = end

    def build(self) -> str:
        enable = f"enable='between(t,{self.start},{self.end})'"
        y_pos = "ih-120"
        return (f"drawbox=x=20:y={y_pos}:w=400:h=80:color=black@0.7:t=fill:{enable},"
                f"drawbox=x=20:y={y_pos}:w=6:h=80:color=0x00FF00:t=fill:{enable},"
                f"drawtext=text='{self.name_text}':fontsize=28:fontcolor=white"
                f":x=41:y={y_pos}+10:{enable},"
                f"drawtext=text='{self.title}':fontsize=18:fontcolor=white@0.7"
                f":x=41:y={y_pos}+45:{enable}")


class EndScreenNode(VideoFilterNode):
    """Video sonu ekran overlay."""

    def __init__(self, text: str = "Thanks for watching!", duration: float = 5.0):
        super().__init__(name="end_screen")
        self.text = text
        self.duration = duration

    def build(self) -> str:
        escaped = self.text.replace("'", "\\'")
        return (f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.5:t=fill"
                f":enable='gte(t,0.00)',"
                f"drawtext=text='{escaped}':fontsize=64:fontcolor=white"
                f":x=(w-tw)/2:y=(h-th)/2")


# ═══════════════════════════════════════════════════════════════
# BUILDER HELPER — ClipSpec'ten FilterChain oluştur
# ═══════════════════════════════════════════════════════════════

def build_chain_from_spec(spec: dict[str, Any]) -> FilterChain:
    """ClipSpec benzeri dict'ten FilterChain oluştur."""
    chain = FilterChain()

    # Scale
    aspect = spec.get("aspect_ratio", "9:16")
    chain.add(ScaleNode(aspect_ratio=aspect))

    # Speed
    speed = spec.get("speed", 1.0)
    chain.add_conditional(speed != 1.0, SpeedNode(speed))

    # Color grading
    preset = spec.get("color_preset", "")
    if preset:
        chain.add(ColorGradingNode(preset=preset))
    else:
        brightness = spec.get("brightness", 0.0)
        contrast = spec.get("contrast", 1.0)
        saturation = spec.get("saturation", 1.0)
        chain.add_conditional(
            any(v != d for v, d in [(brightness, 0.0), (contrast, 1.0), (saturation, 1.0)]),
            ColorGradingNode(brightness=brightness, contrast=contrast, saturation=saturation),
        )

    # Effects
    fx = spec.get("fx", {})
    chain.add_conditional(fx.get("vignette", 0) > 0, VignetteNode(fx["vignette"]))
    chain.add_conditional(fx.get("glow", 0) > 0, GlowNode(fx["glow"]))
    chain.add_conditional(fx.get("sharpen", 0) > 0, SharpenNode(fx["sharpen"]))
    chain.add_conditional(fx.get("film_grain", 0) > 0, FilmGrainNode(fx["film_grain"]))
    chain.add_conditional(fx.get("chromatic_aberration", 0) > 0, ChromaticAberrationNode(fx["chromatic_aberration"]))
    chain.add_conditional(fx.get("shake", 0) > 0, CameraShakeNode(fx["shake"]))

    # Watermark
    wm = spec.get("watermark", {})
    if wm.get("text"):
        chain.add(WatermarkNode(
            text=wm["text"], font_size=wm.get("font_size", 20),
            position=wm.get("position", "bottom_right"),
        ))

    return chain
