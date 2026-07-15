"""
Gelişmiş görsel efekt motoru.
Zoom, Pan, Ken Burns, Slow-mo, Freeze Frame, Vignette, Film Grain.
FFmpeg filter string'leri üretir.
"""
import logging
import math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Keyframe:
    """Tek bir keyframe."""
    time: float      # Saniye
    value: float     # Değer
    easing: str = "linear"  # linear, ease_in, ease_out, ease_in_out


class EffectsEngine:
    """
    FFmpeg filter string üreten görsel efekt motoru.
    """

    def build_zoom_filter(
        self,
        zoom_level: float = 1.5,
        zoom_center: str = "center",
        start_time: float = 0.0,
        end_time: float = 9999.0,
        duration: float = 2.0,
    ) -> str:
        """
        Zoom efekti filter string'i üretir.

        zoom_center: "center", "face", "top", "bottom"
        """
        cx = "iw/2"
        cy = "ih/2"

        if zoom_center == "face":
            # Yüz konumuna zoom (basitleştirilmiş: üst-orta)
            cx = "iw/2"
            cy = "ih/3"

        # zoompan filter: zoom seviyesini zamanla değiştir
        # z: zoom level, x/y: center position
        return (
            f"zoompan=z='min({zoom_level},{zoom_level}*on/({duration}*25))':"
            f"x='{cx}-iw/({zoom_level}*2)':"
            f"y='{cy}-ih/({zoom_level}*2)':"
            f"d={int(duration * 25)}:s=1080x1920:fps=25"
        )

    def build_ken_burns_filter(
        self,
        direction: str = "in",
        zoom_start: float = 1.0,
        zoom_end: float = 1.3,
        pan_x: str = "0",
        pan_y: str = "0",
        duration: float = 5.0,
    ) -> str:
        """
        Ken Burns efekti (yavaş zoom + pan).

        direction: "in" (zoom in) veya "out" (zoom out)
        """
        if direction == "in":
            z_start, z_end = zoom_start, zoom_end
        else:
            z_start, z_end = zoom_end, zoom_start

        frames = int(duration * 25)

        return (
            f"zoompan="
            f"z='{z_start}+({z_end}-{z_start})*on/{frames}':"
            f"x='{pan_x}':"
            f"y='{pan_y}':"
            f"d={frames}:s=1080x1920:fps=25"
        )

    def build_pan_filter(
        self,
        direction: str = "left",
        speed: float = 1.0,
        duration: float = 5.0,
    ) -> str:
        """
        Pan (kaydırma) efekti.

        direction: "left", "right", "up", "down"
        speed: Hız çarpanı
        """
        frames = int(duration * 25)
        pixels_per_frame = int(100 * speed)

        if direction == "left":
            return (
                f"crop=iw-{pixels_per_frame}*on/25:ih:0:0,"
                f"scale=1080:1920"
            )
        elif direction == "right":
            return (
                f"crop=iw-{pixels_per_frame}*on/25:ih:{pixels_per_frame}*on/25:0,"
                f"scale=1080:1920"
            )
        elif direction == "up":
            return (
                f"crop=iw:ih-{pixels_per_frame}*on/25:0:0,"
                f"scale=1080:1920"
            )
        elif direction == "down":
            return (
                f"crop=iw:ih-{pixels_per_frame}*on/25:0:{pixels_per_frame}*on/25,"
                f"scale=1080:1920"
            )

        return "null"

    def build_slow_motion_filter(
        self,
        factor: float = 0.5,
        motion_interpolation: bool = True,
    ) -> str:
        """
        Slow-motion filter.

        factor: 0.5 = yarı hız, 0.25 = çeyrek hız
        motion_interpolation: True ise minterpolate kullanır
        """
        if motion_interpolation:
            # Motion interpolation ile yumuşak slow-mo
            return (
                f"setpts={1.0/factor}*PTS,"
                f"minterpolate=fps=25:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
            )
        else:
            # Basit slow-mo (frame drop)
            return f"setpts={1.0/factor}*PTS"

    def build_speed_ramp_filter(
        self,
        segments: List[Dict],
    ) -> str:
        """
        Hız rampası (değişken hız).

        segments: [{"start": 0, "end": 5, "speed": 1.0},
                   {"start": 5, "end": 8, "speed": 0.3},
                   {"start": 8, "end": 12, "speed": 1.5}]
        """
        if not segments:
            return "null"

        # Her segment için ayrı PTS çarpanı
        # Basitleştirilmiş: sadece ilk segment'i kullan
        seg = segments[0]
        speed = seg.get("speed", 1.0)
        return f"setpts={1.0/speed}*PTS"

    def build_freeze_frame_filter(
        self,
        freeze_at: float = 5.0,
        freeze_duration: float = 2.0,
    ) -> str:
        """
        Freeze frame (dondurma) efekti.

        Belirli bir kareyi dondurur, belirli süre gösterir.
        """
        freeze_frame = int(freeze_at * 25)
        freeze_frames = int(freeze_duration * 25)

        return (
            f"select='eq(n\\,{freeze_frame})',"
            f"setpts=N/25/TB,"
            f"loop={freeze_frames}:1:0"
        )

    def build_shake_filter(
        self,
        intensity: float = 0.5,
        frequency: float = 10.0,
    ) -> str:
        """
        Camera shake efekti.

        intensity: 0-1 arası şiddet
        frequency: Titreşim frekansı (Hz)
        """
        amp_x = int(intensity * 10)
        amp_y = int(intensity * 8)

        return (
            f"crop=iw-{amp_x*2}:ih-{amp_y*2}:"
            f"{amp_x}+sin(t*{frequency})*{amp_x}:"
            f"{amp_y}+cos(t*{frequency*1.3})*{amp_y}"
        )

    def build_vignette_filter(
        self,
        intensity: float = 0.5,
        angle: float = 0.5,
    ) -> str:
        """
        Vignette efekti.

        intensity: 0-1 arası
        """
        # PI/2 → karanlık köşeler, PI/4 → orta, PI/8 → hafif
        vignette_angle = math.pi * (0.25 + (1 - intensity) * 0.75)
        return f"vignette=PI/{vignette_angle:.2f}"

    def build_glow_filter(
        self,
        intensity: float = 0.5,
        radius: int = 3,
    ) -> str:
        """
        Glow (parlama) efekti.
        Yüksek parlaklık bölgelerini yumuşatır.
        """
        return f"unsharp={radius}:{radius}:{intensity * 2}:{radius}:{radius}:0"

    def build_film_grain_filter(
        self,
        intensity: float = 0.3,
    ) -> str:
        """
        Film grain (tanecik) efekti.
        """
        amount = int(intensity * 80)
        return f"noise=alls={amount}:allf=t+u"

    def build_chromatic_aberration_filter(
        self,
        intensity: float = 0.3,
    ) -> str:
        """
        Chromatic aberration (renk sapması) efekti.
        """
        offset = int(intensity * 8)
        return f"rgbashift=rh={offset}:bh=-{offset}:gh={offset//2}"

    def build_letterbox_filter(
        self,
        bar_ratio: float = 0.12,
        color: str = "black",
    ) -> str:
        """
        Sinematik letterbox (siyah bantlar).

        bar_ratio: Üst/alt bant oranı (0-0.5)
        """
        return (
            f"pad=iw:ih+iw*{bar_ratio}:0:iw*{bar_ratio}/2:{color}"
        )

    def build_mirror_filter(
        self,
        axis: str = "horizontal",
    ) -> str:
        """
        Ayna efekti.

        axis: "horizontal" veya "vertical"
        """
        if axis == "horizontal":
            return "hflip"
        elif axis == "vertical":
            return "vflip"
        return "null"

    def build_color_transition_filter(
        self,
        from_preset: str = "none",
        to_preset: str = "cinematic",
        transition_time: float = 2.0,
    ) -> str:
        """
        Renk geçiş efekti (zamanla renk değişimi).
        """
        # Basitleştirilmiş: sadece hedef rengi uygula
        presets = {
            "none": "eq=brightness=0:contrast=1:saturation=1",
            "cinematic": "eq=brightness=-0.05:contrast=1.2:saturation=0.85",
            "vintage": "eq=brightness=0.02:contrast=1.1:saturation=0.7",
            "vibrant": "eq=brightness=0.02:contrast=1.1:saturation=1.3",
        }
        return presets.get(to_preset, presets["none"])

    def combine_filters(self, filters: List[str]) -> str:
        """
        Birden fazla filter string'ini virgülle birleştirir.
        """
        valid = [f for f in filters if f and f != "null"]
        return ",".join(valid) if valid else "null"

    def build_intro_filter(
        self,
        duration: float = 2.0,
        style: str = "fade_black",
    ) -> str:
        """
        Intro efekti.

        style: "fade_black", "fade_white", "zoom_in", "slide_right"
        """
        if style == "fade_black":
            return f"fade=t=in:st=0:d={duration}"
        elif style == "fade_white":
            return (
                f"fade=t=in:st=0:d={duration}:color=white"
            )
        elif style == "zoom_in":
            frames = int(duration * 25)
            return (
                f"zoompan=z='2-on/{frames}':"
                f"x='iw/2-iw/(2*z)':"
                f"y='ih/2-ih/(2*z)':"
                f"d={frames}:s=1080x1920:fps=25"
            )
        elif style == "slide_right":
            return (
                f"crop=iw*on/{int(duration*25)}:ih:0:0,"
                f"scale=1080:1920"
            )

        return "null"

    def build_outro_filter(
        self,
        duration: float = 2.0,
        style: str = "fade_black",
    ) -> str:
        """
        Outro efekti.
        """
        if style == "fade_black":
            return f"fade=t=out:st=0:d={duration}"
        elif style == "fade_white":
            return f"fade=t=out:st=0:d={duration}:color=white"

        return "null"


# Singleton
effects_engine = EffectsEngine()
