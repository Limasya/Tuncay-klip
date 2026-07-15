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
