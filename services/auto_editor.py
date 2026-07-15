"""
Otomatik edit motoru.
Analiz sinyallerinden (duygu, hareket, ses, chat) edit talimatları üretir.
"""
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from services.edit_spec import (
    ClipSpec, TimeRange, SubtitleEntry, SpeedSegment, AudioTrack,
    Watermark, ColorGrading, VisualEffect, ThumbnailSpec,
    Transition, TransitionType, SpeedEffect, SubtitleStyle,
    ColorPreset, AspectRatio, WatermarkPosition,
)

logger = logging.getLogger(__name__)

# Duygu → stil eşleme
EMOTION_STYLE_MAP = {
    "happy": {
        "color_preset": ColorPreset.VIBRANT,
        "subtitle_style": SubtitleStyle.MODERN,
        "speed_effect": SpeedEffect.NONE,
        "brightness": 0.03,
        "saturation": 1.2,
        "contrast": 1.05,
    },
    "excited": {
        "color_preset": ColorPreset.VIBRANT,
        "subtitle_style": SubtitleStyle.ANIMATED_POP,
        "speed_effect": SpeedEffect.RAMP_UP,
        "brightness": 0.05,
        "saturation": 1.3,
        "contrast": 1.1,
    },
    "angry": {
        "color_preset": ColorPreset.HIGH_CONTRAST,
        "subtitle_style": SubtitleStyle.BOLD,
        "speed_effect": SpeedEffect.NONE,
        "brightness": -0.02,
        "saturation": 0.9,
        "contrast": 1.2,
    },
    "sad": {
        "color_preset": ColorPreset.COOL,
        "subtitle_style": SubtitleStyle.MINIMAL,
        "speed_effect": SpeedEffect.SLOW_MO,
        "brightness": -0.05,
        "saturation": 0.7,
        "contrast": 0.95,
        "temperature": -0.3,
    },
    "surprise": {
        "color_preset": ColorPreset.WARM,
        "subtitle_style": SubtitleStyle.NEON,
        "speed_effect": SpeedEffect.FREEZE_FRAME,
        "brightness": 0.02,
        "saturation": 1.1,
        "contrast": 1.1,
    },
    "fear": {
        "color_preset": ColorPreset.CINEMATIC,
        "subtitle_style": SubtitleStyle.CLASSIC,
        "speed_effect": SpeedEffect.NONE,
        "brightness": -0.08,
        "saturation": 0.6,
        "contrast": 1.3,
        "gamma": 0.9,
    },
    "disgust": {
        "color_preset": ColorPreset.DESATURATED,
        "subtitle_style": SubtitleStyle.CLASSIC,
        "speed_effect": SpeedEffect.NONE,
        "brightness": -0.03,
        "saturation": 0.5,
        "contrast": 1.15,
    },
    "neutral": {
        "color_preset": ColorPreset.NONE,
        "subtitle_style": SubtitleStyle.CLASSIC,
        "speed_effect": SpeedEffect.NONE,
    },
}

# Hareket şiddeti → hız
MOTION_SPEED_MAP = {
    "low": (0.9, SpeedEffect.SLOW_MO),
    "medium": (1.0, SpeedEffect.NONE),
    "high": (1.2, SpeedEffect.RAMP_UP),
    "extreme": (1.5, SpeedEffect.RAMP_UP),
}

# Ses enerjisi → ses efekti volümü
AUDIO_SFX_MAP = {
    "low": 0.5,
    "medium": 0.8,
    "high": 1.0,
    "spike": 1.2,
}

# Kategori → temel edit stili
CATEGORY_STYLE_MAP = {
    "other": {
        "music_volume": 0.3,
        "sfx_volume": 0.7,
        "color_preset": ColorPreset.NONE,
        "subtitle_style": SubtitleStyle.CLASSIC,
        "transition": TransitionType.FADE,
    },
    "exciting": {
        "music_volume": 0.4,
        "sfx_volume": 1.0,
        "color_preset": ColorPreset.VIBRANT,
        "subtitle_style": SubtitleStyle.ANIMATED_POP,
        "transition": TransitionType.ZOOM_IN,
    },
    "funny": {
        "music_volume": 0.3,
        "sfx_volume": 0.9,
        "color_preset": ColorPreset.WARM,
        "subtitle_style": SubtitleStyle.BOLD,
        "transition": TransitionType.FADE,
    },
    "emotional": {
        "music_volume": 0.5,
        "sfx_volume": 0.3,
        "color_preset": ColorPreset.CINEMATIC,
        "subtitle_style": SubtitleStyle.MINIMAL,
        "transition": TransitionType.DISSOLVE,
    },
    "rage": {
        "music_volume": 0.35,
        "sfx_volume": 1.2,
        "color_preset": ColorPreset.HIGH_CONTRAST,
        "subtitle_style": SubtitleStyle.BOLD,
        "transition": TransitionType.SLIDE_LEFT,
    },
    "wholesome": {
        "music_volume": 0.4,
        "sfx_volume": 0.2,
        "color_preset": ColorPreset.WARM,
        "subtitle_style": SubtitleStyle.CLASSIC,
        "transition": TransitionType.FADE,
    },
    "skill": {
        "music_volume": 0.35,
        "sfx_volume": 0.7,
        "color_preset": ColorPreset.VIBRANT,
        "subtitle_style": SubtitleStyle.MODERN,
        "transition": TransitionType.ZOOM_IN,
    },
    "fail": {
        "music_volume": 0.25,
        "sfx_volume": 1.0,
        "color_preset": ColorPreset.VINTAGE,
        "subtitle_style": SubtitleStyle.BOLD,
        "transition": TransitionType.FADE_BLACK,
    },
    "victory": {
        "music_volume": 0.5,
        "sfx_volume": 0.8,
        "color_preset": ColorPreset.VIBRANT,
        "subtitle_style": SubtitleStyle.NEON,
        "transition": TransitionType.ZOOM_OUT,
    },
}


class AutoEditor:
    """
    Analiz sinyallerinden otomatik edit talimatları üreten motor.
    """

    def __init__(self):
        self._subtitle_counter = 0

    def generate_edit_spec(
        self,
        source_path: str,
        analysis: Dict,
        category: str = "other",
        aspect_ratio: AspectRatio = AspectRatio.PORTRAIT_9_16,
        resolution: str = "1080p",
        custom_overrides: Optional[Dict] = None,
    ) -> ClipSpec:
        """
        Analiz sonuçlarından tam bir ClipSpec üretir.

        Args:
            source_path: Kaynak video dosyası yolu
            analysis: Analiz sonuçları dict (emotion, motion, audio, chat)
            category: Klip kategorisi
            aspect_ratio: Hedef aspect ratio
            resolution: Hedef çözünürlük
            custom_overrides: AI tarafından sağlanan özel override'lar
        """
        emotion_result = analysis.get("emotion", {})
        motion_result = analysis.get("motion", {})
        audio_result = analysis.get("audio", {})
        chat_result = analysis.get("chat", {})

        dominant_emotion = emotion_result.get("dominant", "neutral")
        emotion_confidence = emotion_result.get("confidence", 0.5)
        motion_level = motion_result.get("level", "medium")
        audio_energy = audio_result.get("energy_level", "medium")
        audio_is_spike = audio_result.get("is_spike", False)

        # Temel stil parametrelerini al
        cat_style = CATEGORY_STYLE_MAP.get(category, CATEGORY_STYLE_MAP["other"])
        emo_style = EMOTION_STYLE_MAP.get(dominant_emotion, EMOTION_STYLE_MAP["neutral"])

        # Color grading oluştur
        color_grading = self._build_color_grading(
            cat_style, emo_style, emotion_confidence
        )

        # Efektleri oluştur
        effects = self._build_effects(motion_level, audio_is_spike)

        # Hız segmentlerini oluştur
        speed_segments = self._build_speed_segments(
            motion_level, dominant_emotion, audio_is_spike
        )

        # Thumbnail zamanını seç
        thumbnail = self._build_thumbnail(analysis, category)

        # Altyazı stilini seç
        subtitle_style = emo_style.get("subtitle_style", SubtitleStyle.CLASSIC)

        # Filigran
        watermark = Watermark(
            text=category.upper(),
            position=WatermarkPosition.BOTTOM_RIGHT,
            opacity=0.5,
        )

        # Geçiş
        transition_type = cat_style.get("transition", TransitionType.FADE)

        # AI override'ları uygula
        if custom_overrides:
            color_grading = self._apply_color_overrides(
                color_grading, custom_overrides.get("color")
            )
            if "subtitle_style" in custom_overrides:
                subtitle_style = SubtitleStyle(custom_overrides["subtitle_style"])

        spec = ClipSpec(
            source_path=source_path,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            color_grading=color_grading,
            effects=effects,
            speed_segments=speed_segments,
            watermark=watermark,
            music_volume=cat_style.get("music_volume", 0.3),
            sfx_volume=cat_style.get("sfx_volume", 0.8),
            thumbnail=thumbnail,
            transition_between=Transition(type=transition_type),
            category=category,
            composite_score=analysis.get("composite_score", 0.0),
            confidence=emotion_confidence,
        )

        logger.info(
            "Edit spec uretildi: emotion=%s, motion=%s, category=%s, "
            "color=%s, speed=%d segment",
            dominant_emotion, motion_level, category,
            color_grading.preset if isinstance(color_grading.preset, str) else color_grading.preset.value,
            len(speed_segments),
        )

        return spec

    def generate_subtitles_from_whisper(
        self,
        whisper_segments: List[Dict],
        style: SubtitleStyle = SubtitleStyle.CLASSIC,
        max_chars_per_line: int = 42,
    ) -> List[SubtitleEntry]:
        """
        Whisper çıktısından altyazı listesi üretir.
        Her segmenti satır satır böler ve stil atar.
        """
        entries = []
        for seg in whisper_segments:
            text = seg.get("text", "").strip()
            if not text:
                continue

            start = seg.get("start", 0.0)
            end = seg.get("end", 0.0)
            words = seg.get("words", [])

            if words:
                # Word-level timing varsa
                lines = self._split_into_lines(words, max_chars_per_line)
                for line_text, line_start, line_end in lines:
                    entries.append(SubtitleEntry(
                        text=line_text,
                        start=line_start,
                        end=line_end,
                        style=style,
                        font_size=self._calc_font_size(style),
                        position="bottom",
                    ))
            else:
                # Sadece segment-level timing
                entries.append(SubtitleEntry(
                    text=text,
                    start=start,
                    end=end,
                    style=style,
                    font_size=self._calc_font_size(style),
                    position="bottom",
                ))

        return entries

    def generate_audio_tracks(
        self,
        analysis: Dict,
        music_library_path: Optional[str] = None,
        sfx_library_path: Optional[str] = None,
    ) -> List[AudioTrack]:
        """
        Analiz sinyallerine göre ses track'leri önerir.
        """
        tracks = []
        audio_result = analysis.get("audio", {})
        emotion_result = analysis.get("emotion", {})
        audio_energy = audio_result.get("energy_level", "medium")

        # Arka plan müziği
        if music_library_path:
            music_track = AudioTrack(
                path=music_library_path,
                volume=0.3,
                fade_in=1.0,
                fade_out=2.0,
                loop=True,
                duck=True,
                duck_target=0.2,
                duck_attack=0.8,
                duck_release=1.0,
            )
            tracks.append(music_track)

        # Ses efektleri
        if sfx_library_path and audio_result.get("is_spike"):
            sfx_track = AudioTrack(
                path=sfx_library_path,
                volume=AUDIO_SFX_MAP.get(audio_energy, 0.8),
                start_at=0.0,
                fade_in=0.0,
                fade_out=0.3,
            )
            tracks.append(sfx_track)

        return tracks

    def merge_analysis_into_edit_spec(
        self,
        base_spec: ClipSpec,
        analysis: Dict,
        whisper_segments: Optional[List[Dict]] = None,
        music_path: Optional[str] = None,
        sfx_path: Optional[str] = None,
    ) -> ClipSpec:
        """
        Mevcut ClipSpec'i analiz verileriyle zenginleştirir.
        """
        # Altyazıları ekle
        if whisper_segments:
            emo_style = EMOTION_STYLE_MAP.get(
                base_spec.category or "neutral", {}
            ).get("subtitle_style", SubtitleStyle.CLASSIC)
            subtitles = self.generate_subtitles_from_whisper(
                whisper_segments, emo_style
            )
            base_spec = base_spec.copy(update={"subtitles": subtitles})

        # Ses track'lerini ekle
        audio_tracks = self.generate_audio_tracks(
            analysis, music_path, sfx_path
        )
        if audio_tracks:
            existing = list(base_spec.audio_tracks)
            existing.extend(audio_tracks)
            base_spec = base_spec.copy(update={"audio_tracks": existing})

        return base_spec

    # --- İç yardımcı fonksiyonlar ---

    def _build_color_grading(
        self, cat_style: Dict, emo_style: Dict, confidence: float
    ) -> ColorGrading:
        """Duygu ve kategori sinyallerinden color grading oluşturur."""
        preset = emo_style.get("color_preset", ColorPreset.NONE)
        if preset == ColorPreset.NONE:
            preset = cat_style.get("color_preset", ColorPreset.NONE)

        # Güven seviyesine göre intensite ayarı
        intensity = min(confidence * 1.2, 1.0)

        return ColorGrading(
            preset=preset,
            brightness=emo_style.get("brightness", 0.0) * intensity,
            contrast=1.0 + (emo_style.get("contrast", 1.0) - 1.0) * intensity,
            saturation=1.0 + (emo_style.get("saturation", 1.0) - 1.0) * intensity,
            gamma=emo_style.get("gamma", 1.0),
            temperature=emo_style.get("temperature", 0.0) * intensity,
        )

    def _build_effects(
        self, motion_level: str, audio_is_spike: bool
    ) -> VisualEffect:
        """Hareket ve ses sinyallerinden görsel efektler üretir."""
        effects = VisualEffect()

        if motion_level in ("high", "extreme"):
            effects = effects.copy(update={
                "shake": 0.3 if motion_level == "extreme" else 0.15,
                "motion_blur": 0.2 if motion_level == "extreme" else 0.1,
            })

        if audio_is_spike:
            effects = effects.copy(update={
                "glow": 0.2,
                "vignette": 0.3,
            })

        return effects

    def _build_speed_segments(
        self, motion_level: str, emotion: str, audio_spike: bool
    ) -> List[SpeedSegment]:
        """Hareket ve duyguya göre hız segmentleri üretir."""
        segments = []
        speed, effect = MOTION_SPEED_MAP.get(motion_level, (1.0, SpeedEffect.NONE))

        if effect != SpeedEffect.NONE:
            segments.append(SpeedSegment(
                time_range=TimeRange(start=0.0, end=9999.0),
                speed=speed,
                effect=effect,
            ))

        if audio_spike and emotion in ("surprise", "excited"):
            segments.append(SpeedSegment(
                time_range=TimeRange(start=0.0, end=9999.0),
                speed=1.0,
                effect=SpeedEffect.FREEZE_FRAME,
            ))

        return segments

    def _build_thumbnail(self, analysis: Dict, category: str) -> ThumbnailSpec:
        """Analiz sinyallerinden thumbnail önerisi üretir."""
        emotion = analysis.get("emotion", {})
        dominant = emotion.get("dominant", "neutral")

        # Heyecan verici anlarda thumbnail daha dikkat çekici olmalı
        add_title = category in ("exciting", "victory", "skill", "rage")
        style = SubtitleStyle.BOLD if add_title else SubtitleStyle.CLASSIC

        return ThumbnailSpec(
            auto=True,
            add_title=add_title,
            style=style,
        )

    def _apply_color_overrides(
        self, base: ColorGrading, overrides: Optional[Dict]
    ) -> ColorGrading:
        """AI tarafından sağlanan renk override'larını uygular."""
        if not overrides:
            return base

        update = {}
        for key in ("brightness", "contrast", "saturation", "gamma",
                     "temperature", "tint"):
            if key in overrides:
                update[key] = overrides[key]
        if "preset" in overrides:
            update["preset"] = ColorPreset(overrides["preset"])

        return base.model_copy(update=update)

    def _split_into_lines(
        self, words: List[Dict], max_chars: int
    ) -> List[Tuple[str, float, float]]:
        """Kelimeleri satırlara böler (word-level timing ile)."""
        lines = []
        current_line = []
        current_start = 0.0
        current_chars = 0

        for word in words:
            text = word.get("word", "").strip()
            if not text:
                continue

            start = word.get("start", 0.0)
            end = word.get("end", 0.0)

            if current_chars + len(text) + 1 > max_chars and current_line:
                line_text = " ".join(current_line)
                lines.append((line_text, current_start, end))
                current_line = []
                current_chars = 0

            if not current_line:
                current_start = start

            current_line.append(text)
            current_chars += len(text) + 1

        if current_line:
            last_end = current_line[-1] if current_line else current_start
            for w in reversed(words):
                if w.get("word", "").strip():
                    last_end = w.get("end", current_start + 2.0)
                    break
            lines.append((" ".join(current_line), current_start, last_end))

        return lines

    def _calc_font_size(self, style: SubtitleStyle) -> int:
        """Stile göre font boyutu hesaplar."""
        sizes = {
            SubtitleStyle.CLASSIC: 48,
            SubtitleStyle.MODERN: 44,
            SubtitleStyle.BOLD: 56,
            SubtitleStyle.NEON: 52,
            SubtitleStyle.MINIMAL: 40,
            SubtitleStyle.ANIMATED_POP: 54,
        }
        return sizes.get(style, 48)


# Singleton
auto_editor = AutoEditor()
