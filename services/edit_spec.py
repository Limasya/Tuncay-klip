"""
ClipSpec v1 - AI edit talimatları için Pydantic modelleri.
AI motorunun ürettiği edit talimatlarını temsil eder.
Pydantic v1 uyumlu.
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


# --- Enums ---

class AspectRatio(str, Enum):
    LANDSCAPE_16_9 = "16:9"
    PORTRAIT_9_16 = "9:16"
    SQUARE_1_1 = "1:1"
    PORTRAIT_4_5 = "4:5"


class TransitionType(str, Enum):
    NONE = "none"
    FADE = "fade"
    DISSOLVE = "dissolve"
    WIPE_LEFT = "wipe_left"
    WIPE_RIGHT = "wipe_right"
    WIPE_UP = "wipe_up"
    WIPE_DOWN = "wipe_down"
    SLIDE_LEFT = "slide_left"
    SLIDE_RIGHT = "slide_right"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    FADE_BLACK = "fade_black"
    FADE_WHITE = "fade_white"


class SpeedEffect(str, Enum):
    NONE = "none"
    SLOW_MO = "slow_mo"
    TIME_LAPSE = "time_lapse"
    RAMP_UP = "ramp_up"
    RAMP_DOWN = "ramp_down"
    FREEZE_FRAME = "freeze_frame"


class WatermarkPosition(str, Enum):
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"
    CENTER = "center"


class SubtitleStyle(str, Enum):
    CLASSIC = "classic"
    MODERN = "modern"
    BOLD = "bold"
    NEON = "neon"
    MINIMAL = "minimal"
    ANIMATED_POP = "animated_pop"


class ColorPreset(str, Enum):
    NONE = "none"
    VIBRANT = "vibrant"
    WARM = "warm"
    COOL = "cool"
    CINEMATIC = "cinematic"
    VINTAGE = "vintage"
    HIGH_CONTRAST = "high_contrast"
    DESATURATED = "desaturated"


# --- Pydantic v1 Config helper ---
class ImmutableConfig:
    allow_mutation = False
    use_enum_values = True


# --- Alt modeller ---

class TimeRange(BaseModel):
    class Config(ImmutableConfig):
        pass

    start: float = Field(ge=0, description="Baslangic saniyesi")
    end: float = Field(ge=0, description="Bitis saniyesi")


class SubtitleEntry(BaseModel):
    class Config(ImmutableConfig):
        pass

    text: str
    start: float
    end: float
    style: SubtitleStyle = SubtitleStyle.CLASSIC
    font_size: int = Field(default=48, ge=12, le=200)
    color: str = Field(default="#FFFFFF")
    bg_color: Optional[str] = None
    position: str = Field(default="bottom")
    animation: Optional[str] = None


class SpeedSegment(BaseModel):
    class Config(ImmutableConfig):
        pass

    time_range: TimeRange
    speed: float = Field(default=1.0, gt=0, le=8.0)
    effect: SpeedEffect = SpeedEffect.NONE
    easing: str = Field(default="linear")


class AudioTrack(BaseModel):
    class Config(ImmutableConfig):
        pass

    path: str
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    start_at: float = Field(default=0.0, ge=0)
    fade_in: float = Field(default=0.0, ge=0)
    fade_out: float = Field(default=0.0, ge=0)
    loop: bool = False
    duck: bool = False
    duck_target: float = Field(default=0.3, ge=0, le=1.0)
    duck_attack: float = Field(default=0.5, ge=0)
    duck_release: float = Field(default=0.5, ge=0)


class Watermark(BaseModel):
    class Config(ImmutableConfig):
        pass

    text: Optional[str] = None
    image_path: Optional[str] = None
    position: WatermarkPosition = WatermarkPosition.BOTTOM_RIGHT
    opacity: float = Field(default=0.7, ge=0, le=1)
    scale: float = Field(default=1.0, ge=0.1, le=3.0)


class ColorGrading(BaseModel):
    class Config(ImmutableConfig):
        pass

    preset: ColorPreset = ColorPreset.NONE
    brightness: float = Field(default=0.0, ge=-1.0, le=1.0)
    contrast: float = Field(default=1.0, ge=0.1, le=3.0)
    saturation: float = Field(default=1.0, ge=0.0, le=3.0)
    gamma: float = Field(default=1.0, ge=0.1, le=5.0)
    temperature: float = Field(default=0.0, ge=-1.0, le=1.0)
    tint: float = Field(default=0.0, ge=-1.0, le=1.0)


class Transition(BaseModel):
    class Config(ImmutableConfig):
        pass

    type: TransitionType = TransitionType.FADE
    duration: float = Field(default=0.5, ge=0.1, le=3.0)
    easing: str = Field(default="ease_in_out")


class VisualEffect(BaseModel):
    class Config(ImmutableConfig):
        pass

    vignette: float = Field(default=0.0, ge=0, le=1)
    glow: float = Field(default=0.0, ge=0, le=1)
    sharpen: float = Field(default=0.0, ge=0, le=5)
    film_grain: float = Field(default=0.0, ge=0, le=1)
    chromatic_aberration: float = Field(default=0.0, ge=0, le=1)
    shake: float = Field(default=0.0, ge=0, le=1)
    motion_blur: float = Field(default=0.0, ge=0, le=1)


class ThumbnailSpec(BaseModel):
    class Config(ImmutableConfig):
        pass

    auto: bool = True
    time_point: Optional[float] = None
    add_title: bool = True
    title_text: Optional[str] = None
    style: SubtitleStyle = SubtitleStyle.BOLD
    overlay_image: Optional[str] = None


# --- Beat Sync ---

class BeatSyncConfig(BaseModel):
    """Beat-senkronize efekt ayarlari."""
    class Config(ImmutableConfig):
        pass

    enabled: bool = False
    audio_path: Optional[str] = None
    bpm: Optional[float] = None
    zoom_on_beat: bool = True
    zoom_level: float = Field(default=1.05, ge=1.0, le=2.0)
    flash_on_beat: bool = False
    flash_color: str = Field(default="white")
    flash_intensity: float = Field(default=0.15, ge=0.0, le=1.0)
    shake_on_beat: bool = False
    shake_intensity: float = Field(default=0.2, ge=0.0, le=1.0)
    speed_variation: bool = False
    slow_on_beat: float = Field(default=0.85, ge=0.5, le=1.0)
    fast_between: float = Field(default=1.15, ge=1.0, le=2.0)
    downbeats_only: bool = False


# --- Word Highlight (Karaoke) ---

class WordHighlightConfig(BaseModel):
    """Kelime vurgulama (karaoke) ayarlari."""
    class Config(ImmutableConfig):
        pass

    enabled: bool = False
    words: List[Dict] = Field(default_factory=list)
    palette: str = Field(default="neon")
    font_size: int = Field(default=52, ge=12, le=200)
    max_chars_per_line: int = Field(default=30, ge=10, le=80)
    position: str = Field(default="bottom")
    outline: float = Field(default=3.0, ge=0, le=10)
    shadow: float = Field(default=2.0, ge=0, le=10)
    animation: str = Field(default="none")  # none, bounce, pop, wave


# --- Sticker/Emoji Overlay ---

class StickerDef(BaseModel):
    """Tek bir sticker tanimi."""
    class Config(ImmutableConfig):
        pass

    emoji: str
    x: float = Field(default=0.5, ge=0.0, le=1.0)
    y: float = Field(default=0.5, ge=0.0, le=1.0)
    start: float = Field(default=0.0, ge=0)
    duration: float = Field(default=2.0, ge=0.1)
    scale: float = Field(default=1.0, ge=0.1, le=5.0)
    animation: str = Field(default="pop")
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)


class StickerOverlayConfig(BaseModel):
    """Sticker/emoji overlay ayarlari."""
    class Config(ImmutableConfig):
        pass

    enabled: bool = False
    stickers: List[StickerDef] = Field(default_factory=list)
    reaction_type: Optional[str] = None  # fire, hype, fail, victory, love, shock
    reaction_start: float = Field(default=0.0, ge=0)
    reaction_duration: float = Field(default=2.0, ge=0.1)
    emoji_rain: bool = False
    emoji_rain_emoji: str = Field(default="fire")
    emoji_rain_start: float = Field(default=0.0, ge=0)
    emoji_rain_duration: float = Field(default=3.0, ge=0.1)
    confetti: bool = False
    confetti_start: float = Field(default=0.0, ge=0)
    confetti_duration: float = Field(default=3.0, ge=0.1)


# --- Lower Third ---

class LowerThirdEntry(BaseModel):
    """Tek bir lower third girdisi."""
    class Config(ImmutableConfig):
        pass

    name: str
    title: str = Field(default="")
    style: str = Field(default="news")
    start_time: float = Field(default=0.0, ge=0)
    duration: float = Field(default=5.0, ge=0.5)
    position: str = Field(default="bottom_left")
    animated: bool = True


class LowerThirdConfig(BaseModel):
    """Lower third grafik ayarlari."""
    class Config(ImmutableConfig):
        pass

    enabled: bool = False
    entries: List[LowerThirdEntry] = Field(default_factory=list)
    scoreboard: bool = False
    scoreboard_player1: str = Field(default="Player 1")
    scoreboard_score1: int = Field(default=0)
    scoreboard_player2: str = Field(default="Player 2")
    scoreboard_score2: int = Field(default=0)
    progress_bar: bool = False
    progress_bar_color: str = Field(default="red")


# --- End Screen ---

class EndScreenConfig(BaseModel):
    """Bitis ekrani (outro) ayarlari."""
    class Config(ImmutableConfig):
        pass

    enabled: bool = False
    template: str = Field(default="subscribe_cta")
    custom_text: Optional[Dict[str, str]] = None
    duration: float = Field(default=5.0, ge=1.0, le=15.0)
    fade_out: bool = True
    fade_out_duration: float = Field(default=2.0, ge=0.5, le=5.0)
    call_to_action: Optional[str] = None  # subscribe, like, comment, share
    cta_position: str = Field(default="bottom_right")


# --- Split Screen ---

class SplitScreenConfig(BaseModel):
    """Bolunmus ekran ayarlari."""
    class Config(ImmutableConfig):
        pass

    enabled: bool = False
    layout: str = Field(default="side_by_side")
    clip_paths: List[str] = Field(default_factory=list)
    gap: int = Field(default=4, ge=0, le=20)
    pip: bool = False
    pip_input: int = Field(default=1)
    pip_position: str = Field(default="bottom_right")
    pip_scale: float = Field(default=0.3, ge=0.1, le=0.5)
    animated: bool = False
    reveal_duration: float = Field(default=0.5, ge=0.1, le=2.0)


# --- Emotion Arc ---

class EmotionSegment(BaseModel):
    """Tek bir emotion segmenti."""
    class Config(ImmutableConfig):
        pass

    start: float = Field(default=0.0, ge=0)
    end: float = Field(default=1.0, ge=0)
    emotion: str = Field(default="neutral")
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)


class EmotionArcConfig(BaseModel):
    """Duygu yayilimi efekt ayarlari."""
    class Config(ImmutableConfig):
        pass

    enabled: bool = False
    segments: List[EmotionSegment] = Field(default_factory=list)
    apply_color: bool = True
    apply_speed: bool = True
    apply_vignette: bool = True


# --- Scene Detection ---

class SceneDetectionConfig(BaseModel):
    """Sahne algilama ayarlari."""
    class Config(ImmutableConfig):
        pass

    enabled: bool = False
    threshold: float = Field(default=0.3, ge=0.1, le=1.0)
    min_scene_duration: float = Field(default=0.5, ge=0.1, le=5.0)
    apply_effects: bool = True
    effect_map: Dict[str, str] = Field(default_factory=dict)
    highlight_reel: bool = False
    max_highlight_duration: float = Field(default=60.0, ge=10, le=300)
    scene_transitions: bool = False
    transition_type: str = Field(default="fade")
    transition_duration: float = Field(default=0.5, ge=0.1, le=2.0)


# --- Ana ClipSpec ---

class ClipSpec(BaseModel):
    """
    AI tarafindan uretilen edit talimati.
    Tek bir klip veya montaj icin tum edit parametrelerini tanimlar.
    """
    class Config(ImmutableConfig):
        pass

    version: str = Field(default="1.0")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Kaynak
    source_path: str
    time_range: Optional[TimeRange] = None

    # Cikti
    output_format: str = Field(default="mp4")
    aspect_ratio: AspectRatio = AspectRatio.PORTRAIT_9_16
    resolution: str = Field(default="1080p")
    crf: int = Field(default=23, ge=0, le=51)

    # Duzenleme talimatlari
    subtitles: List[SubtitleEntry] = Field(default_factory=list)
    speed_segments: List[SpeedSegment] = Field(default_factory=list)
    color_grading: ColorGrading = Field(default_factory=ColorGrading)
    effects: VisualEffect = Field(default_factory=VisualEffect)
    watermark: Optional[Watermark] = None
    transitions: List[Transition] = Field(default_factory=list)

    # Ses
    audio_tracks: List[AudioTrack] = Field(default_factory=list)
    music_volume: float = Field(default=0.3, ge=0, le=2.0)
    sfx_volume: float = Field(default=0.8, ge=0, le=2.0)

    # Thumbnail
    thumbnail: ThumbnailSpec = Field(default_factory=ThumbnailSpec)

    # Montaj (coklu klip)
    clips: List["ClipSpec"] = Field(default_factory=list)
    transition_between: Transition = Field(default_factory=Transition)

    # Gelistirilmis ozellikler
    beat_sync: BeatSyncConfig = Field(default_factory=BeatSyncConfig)
    word_highlight: WordHighlightConfig = Field(default_factory=WordHighlightConfig)
    stickers: StickerOverlayConfig = Field(default_factory=StickerOverlayConfig)
    lower_thirds: LowerThirdConfig = Field(default_factory=LowerThirdConfig)
    end_screen: EndScreenConfig = Field(default_factory=EndScreenConfig)
    split_screen: SplitScreenConfig = Field(default_factory=SplitScreenConfig)
    emotion_arc: EmotionArcConfig = Field(default_factory=EmotionArcConfig)
    scene_detection: SceneDetectionConfig = Field(default_factory=SceneDetectionConfig)

    # AI metadata
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    composite_score: float = Field(default=0.0, ge=0, le=1)
    confidence: float = Field(default=1.0, ge=0, le=1)


class MontageSpec(BaseModel):
    """
    Birden fazla ClipSpec'i birlestiren ust seviye montaj talimati.
    """
    class Config(ImmutableConfig):
        pass

    clips: List[ClipSpec] = Field(default_factory=list)
    transition: Transition = Field(default_factory=Transition)
    title: Optional[str] = None
    intro_duration: float = Field(default=0.0, ge=0)
    outro_duration: float = Field(default=0.0, ge=0)
    background_music: Optional[AudioTrack] = None
    output_path: str = "data/exports/montage.mp4"

    @validator("clips")
    def clips_min_length(cls, v):
        if len(v) < 1:
            raise ValueError("En az 1 klip gerekli")
        return v


# Forward ref
ClipSpec.update_forward_refs()
