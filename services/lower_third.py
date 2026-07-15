"""
Lower third grafik motoru.
Profesyonel alt yazı çubukları, bilgi panelleri, isim levhaları.
FFmpeg drawtext + drawbox ile üretir.
"""
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LowerThirdStyle:
    """Lower third stil tanımı."""
    name: str
    bg_color: str = "black@0.7"
    text_color: str = "white"
    accent_color: str = "red"
    font_size_name: int = 36
    font_size_title: int = 24
    bar_height: int = 80
    bar_y_offset: int = 100
    animation_in: str = "slide_left"  # slide_left, fade, wipe
    animation_out: str = "slide_right"
    duration: float = 5.0


# Hazır lower third stilleri
LT_STYLES = {
    "news": LowerThirdStyle(
        name="news",
        bg_color="black@0.85",
        text_color="white",
        accent_color="red",
        font_size_name=32,
        font_size_title=22,
        bar_height=70,
        bar_y_offset=80,
    ),
    "modern": LowerThirdStyle(
        name="modern",
        bg_color="white@0.9",
        text_color="black",
        accent_color="blue",
        font_size_name=30,
        font_size_title=20,
        bar_height=60,
        bar_y_offset=90,
    ),
    "minimal": LowerThirdStyle(
        name="minimal",
        bg_color="black@0.5",
        text_color="white",
        accent_color="white",
        font_size_name=28,
        font_size_title=18,
        bar_height=50,
        bar_y_offset=100,
    ),
    "gaming": LowerThirdStyle(
        name="gaming",
        bg_color="purple@0.8",
        text_color="white",
        accent_color="cyan",
        font_size_name=34,
        font_size_title=24,
        bar_height=80,
        bar_y_offset=70,
    ),
    "sports": LowerThirdStyle(
        name="sports",
        bg_color="blue@0.85",
        text_color="white",
        accent_color="yellow",
        font_size_name=36,
        font_size_title=24,
        bar_height=75,
        bar_y_offset=85,
    ),
    "cinematic": LowerThirdStyle(
        name="cinematic",
        bg_color="black@0.7",
        text_color="white",
        accent_color="gold",
        font_size_name=30,
        font_size_title=20,
        bar_height=65,
        bar_y_offset=95,
    ),
}


class LowerThirdEngine:
    """
    Lower third grafik motoru.
    FFmpeg drawtext + drawbox ile grafik üretir.
    """

    def __init__(self):
        self._styles = dict(LT_STYLES)

    def generate_lower_third(
        self,
        name: str,
        title: str = "",
        style: str = "news",
        start_time: float = 0.0,
        duration: float = 5.0,
        position: str = "bottom_left",
        video_width: int = 1080,
        video_height: int = 1920,
    ) -> str:
        """
        Lower third için FFmpeg filter string'i üretir.

        drawbox: Arka plan çubuğu
        drawtext: İsim ve unvan
        """
        s = self._styles.get(style, LT_STYLES["news"])

        # Pozisyon hesapla
        pos_map = {
            "bottom_left": (20, video_height - s.bar_y_offset - s.bar_height),
            "bottom_right": (video_width - 400, video_height - s.bar_y_offset - s.bar_height),
            "top_left": (20, s.bar_y_offset),
            "top_right": (video_width - 400, s.bar_y_offset),
        }
        x, y = pos_map.get(position, pos_map["bottom_left"])

        # Bar genişliği (metin uzunluğuna göre)
        bar_width = max(400, len(name) * 18 + 40)

        # Accent bar (sol kenardaki renkli çizgi)
        accent_width = 6

        filters = []

        # 1. Arka plan çubuğu
        filters.append(
            f"drawbox=x={x}:y={y}:"
            f"w={bar_width}:h={s.bar_height}:"
            f"color={s.bg_color}:t=fill"
        )

        # 2. Accent bar (sol kenar)
        filters.append(
            f"drawbox=x={x}:y={y}:"
            f"w={accent_width}:h={s.bar_height}:"
            f"color={s.accent_color}:t=fill"
        )

        # 3. İsim metni
        filters.append(
            f"drawtext=text='{name}':"
            f"fontsize={s.font_size_name}:"
            f"fontcolor={s.text_color}:"
            f"x={x + accent_width + 15}:"
            f"y={y + 10}"
        )

        # 4. Unvan (varsa)
        if title:
            filters.append(
                f"drawtext=text='{title}':"
                f"fontsize={s.font_size_title}:"
                f"fontcolor={s.text_color}@0.7:"
                f"x={x + accent_width + 15}:"
                f"y={y + s.font_size_name + 15}"
            )

        return ",".join(filters)

    def generate_animated_lower_third(
        self,
        name: str,
        title: str = "",
        style: str = "news",
        start_time: float = 0.0,
        duration: float = 5.0,
        animation_in: str = "slide_left",
        animation_out: str = "slide_right",
    ) -> str:
        """
        Animasyonlu lower third üretir.
        Slide in/out, fade in/out.
        """
        s = self._styles.get(style, LT_STYLES["news"])

        if animation_in == "slide_left":
            # Sol kayarak girişi enable et
            enable = f"between(t,{start_time:.2f},{start_time + duration:.2f})"
        elif animation_in == "fade":
            enable = f"between(t,{start_time:.2f},{start_time + duration:.2f})"
        else:
            enable = f"between(t,{start_time:.2f},{start_time + duration:.2f})"

        # Basitleştirilmiş: enable/disable ile görünürlük
        base_filter = self.generate_lower_third(
            name, title, style, start_time, duration
        )

        # Her drawtext/drawbox'a enable ekle
        parts = base_filter.split(",")
        enabled_parts = []
        for part in parts:
            if "drawtext" in part or "drawbox" in part:
                part = part.replace(
                    "drawtext=",
                    f"drawtext=enable='{enable}':"
                ).replace(
                    "drawbox=",
                    f"drawbox=enable='{enable}':"
                )
            enabled_parts.append(part)

        return ",".join(enabled_parts)

    def generate_speaker_card(
        self,
        name: str,
        title: str = "",
        organization: str = "",
        avatar_path: Optional[str] = None,
        style: str = "modern",
        start_time: float = 0.0,
        duration: float = 5.0,
    ) -> str:
        """
        Konuşmacı kartı üretir.
        İsim + unvan + kurum + avatar.
        """
        s = self._styles.get(style, LT_STYLES["modern"])

        filters = []

        # Arka plan paneli
        filters.append(
            f"drawbox=x=20:y=ih-200:w=500:h=160:"
            f"color={s.bg_color}:t=fill"
        )

        # İsim
        filters.append(
            f"drawtext=text='{name}':"
            f"fontsize={s.font_size_name}:"
            f"fontcolor={s.text_color}:"
            f"x=40:y=ih-190"
        )

        # Unvan
        if title:
            filters.append(
                f"drawtext=text='{title}':"
                f"fontsize={s.font_size_title}:"
                f"fontcolor={s.text_color}@0.8:"
                f"x=40:y=ih-{190 - s.font_size_name - 5}"
            )

        # Kurum
        if organization:
            filters.append(
                f"drawtext=text='{organization}':"
                f"fontsize={s.font_size_title - 4}:"
                f"fontcolor={s.accent_color}:"
                f"x=40:y=ih-{190 - s.font_size_name - s.font_size_title - 10}"
            )

        return ",".join(filters)

    def generate_scoreboard(
        self,
        player1: str,
        score1: int,
        player2: str,
        score2: int,
        style: str = "sports",
    ) -> str:
        """
        Skor tablosu üretir.
        """
        s = self._styles.get(style, LT_STYLES["sports"])

        filters = []

        # Arka plan
        filters.append(
            f"drawbox=x=0:y=20:w=iw:h=120:"
            f"color=black@0.7:t=fill"
        )

        # Sol taraf: Oyuncu 1 + skor
        filters.append(
            f"drawtext=text='{player1}':"
            f"fontsize={s.font_size_name}:"
            f"fontcolor=white:"
            f"x=30:y=50"
        )
        filters.append(
            f"drawtext=text='{score1}':"
            f"fontsize=48:"
            f"fontcolor={s.accent_color}:"
            f"x=30:y=80"
        )

        # Sağ taraf: Oyuncu 2 + skor
        filters.append(
            f"drawtext=text='{player2}':"
            f"fontsize={s.font_size_name}:"
            f"fontcolor=white:"
            f"x=w-tw-30:y=50"
        )
        filters.append(
            f"drawtext=text='{score2}':"
            f"fontsize=48:"
            f"fontcolor={s.accent_color}:"
            f"x=w-tw-30:y=80"
        )

        # VS
        filters.append(
            f"drawtext=text='VS':"
            f"fontsize=28:"
            f"fontcolor=white@0.5:"
            f"x=(w-tw)/2:y=60"
        )

        return ",".join(filters)

    def generate_progress_bar(
        self,
        progress: float,
        bar_color: str = "red",
        bg_color: str = "white@0.3",
        y_position: int = -30,
        height: int = 6,
    ) -> str:
        """
        İlerleme çubuğu üretir.
        """
        # Tam genişlik = iw
        filled_width = f"iw*{progress:.4f}"

        return (
            f"drawbox=x=0:y=ih+{y_position}:w=iw:h={height}:"
            f"color={bg_color}:t=fill,"
            f"drawbox=x=0:y=ih+{y_position}:w={filled_width}:h={height}:"
            f"color={bar_color}:t=fill"
        )

    def get_available_styles(self) -> List[str]:
        """Mevcut stil isimlerini döndürür."""
        return list(self._styles.keys())

    def register_style(self, name: str, style: LowerThirdStyle):
        """Özel stil kaydeder."""
        self._styles[name] = style


# Singleton
lower_third = LowerThirdEngine()
