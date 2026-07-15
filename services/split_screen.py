"""
Split screen (bölünmüş ekran) motoru.
Çoklu klip yan yana/üst üste görüntüleme, grid layouts.
FFmpeg xstack, overlay, crop ile üretir.
"""
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SplitLayout:
    """Split screen yerleşim tanımı."""
    name: str
    columns: int
    rows: int
    descriptions: List[str]  # Her hücre için açıklama


# Hazır yerleşimler
SPLIT_LAYOUTS = {
    "side_by_side": SplitLayout(
        name="side_by_side", columns=2, rows=1,
        descriptions=["Sol", "Sağ"],
    ),
    "top_bottom": SplitLayout(
        name="top_bottom", columns=1, rows=2,
        descriptions=["Üst", "Alt"],
    ),
    "grid_2x2": SplitLayout(
        name="grid_2x2", columns=2, rows=2,
        descriptions=["Sol Üst", "Sağ Üst", "Sol Alt", "Sağ Alt"],
    ),
    "grid_3x3": SplitLayout(
        name="grid_3x3", columns=3, rows=3,
        descriptions=["1", "2", "3", "4", "5", "6", "7", "8", "9"],
    ),
    "pip_left": SplitLayout(
        name="pip_left", columns=2, rows=1,
        descriptions=["Ana (büyük)", "PiP (küçük)"],
    ),
    "pip_right": SplitLayout(
        name="pip_right", columns=2, rows=1,
        descriptions=["PiP (küçük)", "Ana (büyük)"],
    ),
    "triptych": SplitLayout(
        name="triptych", columns=3, rows=1,
        descriptions=["Sol", "Orta", "Sağ"],
    ),
    "diagonal": SplitLayout(
        name="diagonal", columns=2, rows=2,
        descriptions=["Sol Üst", "Sağ Üst", "Sol Alt", "Sağ Alt"],
    ),
}


class SplitScreenEngine:
    """
    Split screen motoru.
    FFmpeg xstack, overlay, crop ile çoklu klip yerleşimi.
    """

    def __init__(self):
        self._layouts = dict(SPLIT_LAYOUTS)

    def generate_split_filter(
        self,
        layout: str,
        video_width: int = 1080,
        video_height: int = 1920,
        gap: int = 4,
    ) -> str:
        """
        Split screen FFmpeg filter_complex string'i üretir.

        Returns: filter_complex string (input'lar hariç)
        """
        l = self._layouts.get(layout, SPLIT_LAYOUTS["side_by_side"])

        cell_w = (video_width - gap * (l.columns + 1)) // l.columns
        cell_h = (video_height - gap * (l.rows + 1)) // l.rows

        filters = []
        for i in range(l.columns * l.rows):
            row = i // l.columns
            col = i % l.columns

            x = gap + col * (cell_w + gap)
            y = gap + row * (cell_h + gap)

            filters.append(
                f"[{i}:v]scale={cell_w}:{cell_h}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={cell_w}:{cell_h}:(ow-iw)/2:(oh-ih)/2:black,"
                f"setsar=1[v{i}]"
            )

        # xstack ile birleştir
        input_labels = "".join(f"[v{i}]" for i in range(l.columns * l.rows))
        layout_str = self._build_xstack_layout(l.columns, l.rows, cell_w, cell_h, gap)

        filters.append(
            f"{input_labels}xstack=inputs={l.columns * l.rows}:"
            f"layout={layout_str}"
        )

        return ";".join(filters)

    def generate_side_by_side(
        self,
        video_width: int = 1080,
        video_height: int = 1920,
        gap: int = 4,
    ) -> str:
        """Yan yana split screen."""
        cell_w = (video_width - gap * 3) // 2
        cell_h = video_height - gap * 2

        return (
            f"[0:v]scale={cell_w}:{cell_h}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={cell_w}:{cell_h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1[v0];"
            f"[1:v]scale={cell_w}:{cell_h}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={cell_w}:{cell_h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1[v1];"
            f"[v0][v1]xstack=inputs=2:"
            f"layout={gap}|0+{cell_w + gap * 2}|0"
        )

    def generate_grid_2x2(
        self,
        video_width: int = 1080,
        video_height: int = 1920,
        gap: int = 4,
    ) -> str:
        """2x2 grid split screen."""
        cell_w = (video_width - gap * 3) // 2
        cell_h = (video_height - gap * 3) // 2

        filters = []
        for i in range(4):
            row = i // 2
            col = i % 2
            x = gap + col * (cell_w + gap)
            y = gap + row * (cell_h + gap)
            filters.append(
                f"[{i}:v]scale={cell_w}:{cell_h}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={cell_w}:{cell_h}:(ow-iw)/2:(oh-ih)/2:black,"
                f"setsar=1[v{i}]"
            )

        layout = (
            f"{gap}|0+{cell_w + gap * 2}|0+"
            f"{gap}|{cell_h + gap * 2}"
        )
        filters.append(
            f"[v0][v1][v2][v3]xstack=inputs=4:layout={layout}"
        )

        return ";".join(filters)

    def generate_pip(
        self,
        main_input: int = 0,
        pip_input: int = 1,
        pip_position: str = "bottom_right",
        pip_scale: float = 0.3,
        video_width: int = 1080,
        video_height: int = 1920,
        gap: int = 20,
    ) -> str:
        """
        Picture-in-Picture (PiP) üretir.
        Ana video + küçük.overlay video.
        """
        pip_w = int(video_width * pip_scale)
        pip_h = int(video_height * pip_scale)

        pos_map = {
            "top_left": (gap, gap),
            "top_right": (video_width - pip_w - gap, gap),
            "bottom_left": (gap, video_height - pip_h - gap),
            "bottom_right": (video_width - pip_w - gap, video_height - pip_h - gap),
        }
        px, py = pos_map.get(pip_position, pos_map["bottom_right"])

        return (
            f"[{pip_input}:v]scale={pip_w}:{pip_h}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={pip_w}:{pip_h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"border=2:bordercolor=white[pip];"
            f"[{main_input}:v][pip]overlay={px}:{py}"
        )

    def generate_animated_grid(
        self,
        layout: str,
        reveal_duration: float = 0.5,
        video_width: int = 1080,
        video_height: int = 1920,
    ) -> str:
        """
        Animasyonlu grid (hücreler sırayla görünür).
        """
        l = self._layouts.get(layout, SPLIT_LAYOUTS["grid_2x2"])
        cell_w = video_width // l.columns
        cell_h = video_height // l.rows

        filters = []
        for i in range(l.columns * l.rows):
            row = i // l.columns
            col = i % l.columns

            x = col * cell_w
            y = row * cell_h

            delay = i * reveal_duration

            # Scale + fade in
            filters.append(
                f"[{i}:v]scale={cell_w}:{cell_h}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={cell_w}:{cell_h}:(ow-iw)/2:(oh-ih)/2:black,"
                f"fade=t=in:st={delay:.2f}:d={reveal_duration}[v{i}]"
            )

        input_labels = "".join(f"[v{i}]" for i in range(l.columns * l.rows))
        layout_str = self._build_xstack_layout(
            l.columns, l.rows, cell_w, cell_h, 0
        )

        filters.append(
            f"{input_labels}xstack=inputs={l.columns * l.rows}:"
            f"layout={layout_str}"
        )

        return ";".join(filters)

    def get_available_layouts(self) -> List[str]:
        """Mevcut yerleşim isimlerini döndürür."""
        return list(self._layouts.keys())

    def _build_xstack_layout(
        self, cols: int, rows: int, cell_w: int, cell_h: int, gap: int
    ) -> str:
        """Xstack layout string'i üretir."""
        positions = []
        for row in range(rows):
            for col in range(cols):
                x = gap + col * (cell_w + gap)
                y = gap + row * (cell_h + gap)
                positions.append(f"{x}|{y}")
        return "+".join(positions)


# Singleton
split_screen = SplitScreenEngine()
