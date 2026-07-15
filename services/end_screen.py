"""
End screen/outro motoru.
Otomatik bitiş ekranları, abone ol butonları, teşekkür mesajları.
"""
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class EndScreenTemplate:
    """End screen şablonu."""
    name: str
    style: str        # "subscribe", "thanks", "next_video", "minimal"
    duration: float   # Saniye
    elements: List[Dict]  # Grafik elementler


# Hazır şablonlar
END_SCREEN_TEMPLATES = {
    "subscribe_cta": EndScreenTemplate(
        name="subscribe_cta",
        style="subscribe",
        duration=5.0,
        elements=[
            {"type": "text", "text": "ABONE OL!", "x": 0.5, "y": 0.3,
             "size": 72, "color": "red"},
            {"type": "text", "text": "Bildirim zilini açın", "x": 0.5, "y": 0.45,
             "size": 36, "color": "white"},
            {"type": "circle", "x": 0.5, "y": 0.6, "radius": 50,
             "color": "red@0.8"},
        ],
    ),
    "thanks_watching": EndScreenTemplate(
        name="thanks_watching",
        style="thanks",
        duration=4.0,
        elements=[
            {"type": "text", "text": "İZLEDİĞİNİZ İÇİN TEŞEKKÜRLER",
             "x": 0.5, "y": 0.4, "size": 48, "color": "white"},
            {"type": "text", "text": "Like ve Subscribe!", "x": 0.5, "y": 0.55,
             "size": 32, "color": "yellow"},
        ],
    ),
    "next_video": EndScreenTemplate(
        name="next_video",
        style="next_video",
        duration=6.0,
        elements=[
            {"type": "box", "x": 0.1, "y": 0.2, "w": 0.35, "h": 0.5,
             "color": "black@0.6", "border": "white"},
            {"type": "box", "x": 0.55, "y": 0.2, "w": 0.35, "h": 0.5,
             "color": "black@0.6", "border": "white"},
            {"type": "text", "text": "Önceki Video", "x": 0.275, "y": 0.75,
             "size": 24, "color": "white"},
            {"type": "text", "text": "Sonraki Video", "x": 0.725, "y": 0.75,
             "size": 24, "color": "white"},
            {"type": "text", "text": "İZLEMEYE DEVAM EDİN",
             "x": 0.5, "y": 0.1, "size": 36, "color": "white"},
        ],
    ),
    "minimal_outro": EndScreenTemplate(
        name="minimal_outro",
        style="minimal",
        duration=3.0,
        elements=[
            {"type": "text", "text": "Son", "x": 0.5, "y": 0.5,
             "size": 64, "color": "white"},
        ],
    ),
    "gaming_outro": EndScreenTemplate(
        name="gaming_outro",
        style="gaming",
        duration=5.0,
        elements=[
            {"type": "text", "text": "GG WP", "x": 0.5, "y": 0.3,
             "size": 80, "color": "cyan"},
            {"type": "text", "text": "Like + Subscribe =更多 CONTENT",
             "x": 0.5, "y": 0.5, "size": 32, "color": "white"},
            {"type": "text", "text": "@channelname",
             "x": 0.5, "y": 0.65, "size": 28, "color": "yellow"},
        ],
    ),
    "social_media": EndScreenTemplate(
        name="social_media",
        style="social",
        duration=5.0,
        elements=[
            {"type": "text", "text": "Bizi Takip Edin",
             "x": 0.5, "y": 0.3, "size": 40, "color": "white"},
            {"type": "text", "text": "@tiktok | @instagram | @youtube",
             "x": 0.5, "y": 0.5, "size": 28, "color": "cyan"},
            {"type": "text", "text": "Link bio'da!",
             "x": 0.5, "y": 0.65, "size": 24, "color": "yellow"},
        ],
    ),
}


class EndScreenEngine:
    """
    End screen/outro motoru.
    FFmpeg drawtext + drawbox ile bitiş ekranları üretir.
    """

    def __init__(self):
        self._templates = dict(END_SCREEN_TEMPLATES)

    def generate_end_screen(
        self,
        template: str = "subscribe_cta",
        custom_text: Optional[Dict[str, str]] = None,
        video_width: int = 1080,
        video_height: int = 1920,
    ) -> str:
        """
        End screen FFmpeg filter string'i üretir.
        """
        t = self._templates.get(template, END_SCREEN_TEMPLATES["subscribe_cta"])

        filters = []

        # Karartma overlay (arka plan)
        filters.append(
            f"drawbox=x=0:y=0:w=iw:h=ih:"
            f"color=black@0.5:t=fill:"
            f"enable='gte(t,{0:.2f})'"
        )

        for elem in t.elements:
            x = int(elem["x"] * video_width)
            y = int(elem["y"] * video_height)
            etype = elem.get("type", "text")

            if etype == "text":
                text = elem.get("text", "")
                if custom_text and text in custom_text:
                    text = custom_text[text]

                size = elem.get("size", 36)
                color = elem.get("color", "white")

                filters.append(
                    f"drawtext=text='{text}':"
                    f"fontsize={size}:"
                    f"fontcolor={color}:"
                    f"x={x - size * len(text) // 4}:y={y}"
                )

            elif etype == "box":
                w = int(elem.get("w", 0.3) * video_width)
                h = int(elem.get("h", 0.3) * video_height)
                color = elem.get("color", "black@0.6")
                border_color = elem.get("border", "white")

                filters.append(
                    f"drawbox=x={x}:y={y}:w={w}:h={h}:"
                    f"color={color}:t=fill"
                )
                filters.append(
                    f"drawbox=x={x}:y={y}:w={w}:h={h}:"
                    f"color={border_color}:t=3"
                )

            elif etype == "circle":
                radius = elem.get("radius", 50)
                color = elem.get("color", "red@0.8")

                # Basitleştirilmiş: drawbox ile daire
                filters.append(
                    f"drawbox=x={x - radius}:y={y - radius}:"
                    f"w={radius * 2}:h={radius * 2}:"
                    f"color={color}:t=fill"
                )

        return ",".join(filters)

    def generate_fade_out_overlay(
        self,
        start_time: float,
        duration: float = 2.0,
        fade_color: str = "black",
    ) -> str:
        """
        Fade out overlay üretir.
        Video biterken ekranı karartır.
        """
        return (
            f"drawbox=x=0:y=0:w=iw:h=ih:"
            f"color={fade_color}@0.5*t/{duration}:t=fill:"
            f"enable='between(t,{start_time:.2f},{start_time + duration:.2f})'"
        )

    def generate_progress_overlay(
        self,
        total_duration: float,
        current_time: float,
        bar_color: str = "red",
        bg_color: str = "white@0.3",
    ) -> str:
        """
        İlerleme çubuğu overlay'i üretir.
        """
        progress = current_time / total_duration if total_duration > 0 else 0
        filled_width = f"iw*{progress:.4f}"

        return (
            f"drawbox=x=0:y=ih-30:w=iw:h=6:"
            f"color={bg_color}:t=fill,"
            f"drawbox=x=0:y=ih-30:w={filled_width}:h=6:"
            f"color={bar_color}:t=fill"
        )

    def generate_call_to_action(
        self,
        action: str = "subscribe",
        position: str = "bottom_right",
        video_width: int = 1080,
        video_height: int = 1920,
    ) -> str:
        """
        Call-to-action overlay'i üretir.
        """
        actions = {
            "subscribe": {"text": "ABONE OL", "color": "red", "size": 28},
            "like": {"text": "BEĞEN", "color": "blue", "size": 28},
            "comment": {"text": "YORUM YAP", "color": "green", "size": 24},
            "share": {"text": "PAYLAŞ", "color": "orange", "size": 24},
        }

        a = actions.get(action, actions["subscribe"])

        pos_map = {
            "bottom_right": (video_width - 200, video_height - 100),
            "bottom_left": (20, video_height - 100),
            "top_right": (video_width - 200, 80),
            "top_left": (20, 80),
        }
        x, y = pos_map.get(position, pos_map["bottom_right"])

        return (
            f"drawbox=x={x}:y={y}:w=180:h=60:"
            f"color={a['color']}:t=fill,"
            f"drawtext=text='{a['text']}':"
            f"fontsize={a['size']}:"
            f"fontcolor=white:"
            f"x={x + 20}:y={y + 15}"
        )

    def get_available_templates(self) -> List[str]:
        """Mevcut şablon isimlerini döndürür."""
        return list(self._templates.keys())

    def register_template(self, name: str, template: EndScreenTemplate):
        """Özel şablon kaydeder."""
        self._templates[name] = template


# Singleton
end_screen = EndScreenEngine()
