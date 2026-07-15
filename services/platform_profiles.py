"""
Platform export profilleri.
Her sosyal medya platformu için optimize edilmiş export ayarları.
"""
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PlatformProfile:
    """Platform bazlı export profil."""
    name: str
    display_name: str
    aspect_ratio: str           # "9:16", "16:9", "1:1", "4:5"
    width: int
    height: int
    max_duration: int           # Saniye
    max_file_size_mb: int
    video_codec: str
    audio_codec: str
    video_bitrate: str          # "8M", "5M"
    audio_bitrate: str          # "192k", "128k"
    fps: int
    crf: int
    preset: str                 # "medium", "fast"
    extra_args: List[str] = field(default_factory=list)
    supports_subtitles: bool = True
    supports_music: bool = True
    recommended_subtitle_style: str = "bold"
    max_subtitle_chars: int = 100
    description: str = ""


# Platform profilleri
PLATFORM_PROFILES = {
    "tiktok": PlatformProfile(
        name="tiktok",
        display_name="TikTok",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        max_duration=180,
        max_file_size_mb=287,
        video_codec="libx264",
        audio_codec="aac",
        video_bitrate="8M",
        audio_bitrate="192k",
        fps=30,
        crf=23,
        preset="medium",
        extra_args=["-movflags", "+faststart"],
        recommended_subtitle_style="animated_pop",
        max_subtitle_chars=80,
        description="TikTok: 9:16, max 3dk, 287MB",
    ),
    "youtube_shorts": PlatformProfile(
        name="youtube_shorts",
        display_name="YouTube Shorts",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        max_duration=60,
        max_file_size_mb=256,
        video_codec="libx264",
        audio_codec="aac",
        video_bitrate="8M",
        audio_bitrate="192k",
        fps=30,
        crf=22,
        preset="medium",
        extra_args=["-movflags", "+faststart"],
        recommended_subtitle_style="bold",
        max_subtitle_chars=100,
        description="YouTube Shorts: 9:16, max 60sn",
    ),
    "youtube": PlatformProfile(
        name="youtube",
        display_name="YouTube",
        aspect_ratio="16:9",
        width=1920,
        height=1080,
        max_duration=43200,
        max_file_size_mb=12288,
        video_codec="libx264",
        audio_codec="aac",
        video_bitrate="12M",
        audio_bitrate="192k",
        fps=30,
        crf=20,
        preset="medium",
        extra_args=["-movflags", "+faststart"],
        recommended_subtitle_style="classic",
        max_subtitle_chars=120,
        description="YouTube: 16:9, max 12 saat",
    ),
    "youtube_long": PlatformProfile(
        name="youtube_long",
        display_name="YouTube Long",
        aspect_ratio="16:9",
        width=1920,
        height=1080,
        max_duration=43200,
        max_file_size_mb=12288,
        video_codec="libx264",
        audio_codec="aac",
        video_bitrate="12M",
        audio_bitrate="192k",
        fps=30,
        crf=20,
        preset="medium",
        extra_args=["-movflags", "+faststart"],
        recommended_subtitle_style="classic",
        max_subtitle_chars=120,
        description="YouTube Long: 16:9",
    ),
    "instagram_reels": PlatformProfile(
        name="instagram_reels",
        display_name="Instagram Reels",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        max_duration=90,
        max_file_size_mb=250,
        video_codec="libx264",
        audio_codec="aac",
        video_bitrate="6M",
        audio_bitrate="128k",
        fps=30,
        crf=23,
        preset="fast",
        extra_args=["-movflags", "+faststart"],
        recommended_subtitle_style="modern",
        max_subtitle_chars=100,
        description="Instagram Reels: 9:16, max 90sn",
    ),
    "instagram_feed": PlatformProfile(
        name="instagram_feed",
        display_name="Instagram Feed",
        aspect_ratio="1:1",
        width=1080,
        height=1080,
        max_duration=60,
        max_file_size_mb=250,
        video_codec="libx264",
        audio_codec="aac",
        video_bitrate="5M",
        audio_bitrate="128k",
        fps=30,
        crf=23,
        preset="fast",
        extra_args=["-movflags", "+faststart"],
        recommended_subtitle_style="minimal",
        max_subtitle_chars=80,
        description="Instagram Feed: 1:1, max 60sn",
    ),
    "instagram_story": PlatformProfile(
        name="instagram_story",
        display_name="Instagram Story",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        max_duration=15,
        max_file_size_mb=100,
        video_codec="libx264",
        audio_codec="aac",
        video_bitrate="5M",
        audio_bitrate="128k",
        fps=30,
        crf=23,
        preset="fast",
        extra_args=["-movflags", "+faststart"],
        recommended_subtitle_style="animated_pop",
        max_subtitle_chars=60,
        description="Instagram Story: 9:16, max 15sn",
    ),
    "kick": PlatformProfile(
        name="kick",
        display_name="Kick",
        aspect_ratio="16:9",
        width=1920,
        height=1080,
        max_duration=600,
        max_file_size_mb=1024,
        video_codec="libx264",
        audio_codec="aac",
        video_bitrate="8M",
        audio_bitrate="192k",
        fps=60,
        crf=21,
        preset="medium",
        extra_args=["-movflags", "+faststart"],
        recommended_subtitle_style="bold",
        max_subtitle_chars=120,
        description="Kick: 16:9, max 60sn highlight",
    ),
    "twitter": PlatformProfile(
        name="twitter",
        display_name="Twitter/X",
        aspect_ratio="16:9",
        width=1280,
        height=720,
        max_duration=140,
        max_file_size_mb=512,
        video_codec="libx264",
        audio_codec="aac",
        video_bitrate="5M",
        audio_bitrate="128k",
        fps=30,
        crf=23,
        preset="fast",
        extra_args=["-movflags", "+faststart"],
        recommended_subtitle_style="minimal",
        max_subtitle_chars=100,
        description="Twitter: 16:9, max 140sn, 512MB",
    ),
    "facebook_reels": PlatformProfile(
        name="facebook_reels",
        display_name="Facebook Reels",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        max_duration=90,
        max_file_size_mb=250,
        video_codec="libx264",
        audio_codec="aac",
        video_bitrate="6M",
        audio_bitrate="128k",
        fps=30,
        crf=23,
        preset="fast",
        extra_args=["-movflags", "+faststart"],
        recommended_subtitle_style="bold",
        max_subtitle_chars=100,
        description="Facebook Reels: 9:16, max 90sn",
    ),
    "linkedin": PlatformProfile(
        name="linkedin",
        display_name="LinkedIn",
        aspect_ratio="1:1",
        width=1080,
        height=1080,
        max_duration=600,
        max_file_size_mb=200,
        video_codec="libx264",
        audio_codec="aac",
        video_bitrate="5M",
        audio_bitrate="128k",
        fps=30,
        crf=23,
        preset="medium",
        extra_args=["-movflags", "+faststart"],
        recommended_subtitle_style="classic",
        max_subtitle_chars=100,
        description="LinkedIn: 1:1, max 10dk",
    ),
}


class PlatformExportManager:
    """
    Platform bazlı export yöneticisi.
    """

    def __init__(self):
        self._profiles = dict(PLATFORM_PROFILES)

    def get_profile(self, platform: str) -> Optional[PlatformProfile]:
        """Platform profilini döndürür."""
        return self._profiles.get(platform.lower())

    def get_all_profiles(self) -> Dict[str, PlatformProfile]:
        """Tüm profilleri döndürür."""
        return dict(self._profiles)

    def get_profiles_for_aspect(self, aspect_ratio: str) -> List[PlatformProfile]:
        """Belirli aspect ratio'ya sahip platformları döndürür."""
        return [
            p for p in self._profiles.values()
            if p.aspect_ratio == aspect_ratio
        ]

    def build_ffmpeg_args(
        self,
        platform: str,
        input_path: str,
        output_path: str,
    ) -> List[str]:
        """
        Platform için FFmpeg komut argümanları üretir.
        """
        profile = self.get_profile(platform)
        if not profile:
            logger.warning("Bilinmeyen platform: %s, mp4 varsayılıyor", platform)
            profile = self._profiles["tiktok"]

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-c:v", profile.video_codec,
            "-c:a", profile.audio_codec,
            "-b:v", profile.video_bitrate,
            "-b:a", profile.audio_bitrate,
            "-r", str(profile.fps),
            "-crf", str(profile.crf),
            "-preset", profile.preset,
        ]

        # Scale filter
        cmd.extend(["-vf", f"scale={profile.width}:{profile.height}:"
                    "force_original_aspect_ratio=decrease,"
                    f"pad={profile.width}:{profile.height}:"
                    "(ow-iw)/2:(oh-ih)/2:black"])

        cmd.extend(profile.extra_args)
        cmd.append(output_path)

        return cmd

    def validate_clip(
        self,
        platform: str,
        duration: float,
        file_size_mb: float,
        width: int,
        height: int,
    ) -> Dict:
        """
        Klibin platform uyumluluğunu doğrular.

        Returns:
            {"valid": bool, "issues": [str]}
        """
        profile = self.get_profile(platform)
        if not profile:
            return {"valid": False, "issues": ["Bilinmeyen platform"]}

        issues = []

        if duration > profile.max_duration:
            issues.append(
                f"Süre çok uzun: {duration:.0f}s > {profile.max_duration}s"
            )

        if file_size_mb > profile.max_file_size_mb:
            issues.append(
                f"Dosya boyutu çok büyük: {file_size_mb:.0f}MB > "
                f"{profile.max_file_size_mb}MB"
            )

        if width != profile.width or height != profile.height:
            issues.append(
                f"Çözünürlük uyumsuz: {width}x{height} != "
                f"{profile.width}x{profile.height}"
            )

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "profile": profile.display_name,
        }

    def recommend_platform(
        self,
        duration: float,
        aspect_ratio: str = "9:16",
    ) -> List[str]:
        """
        Süreye ve aspect ratio'ya göre uygun platformları önerir.
        """
        candidates = []
        for name, profile in self._profiles.items():
            if profile.aspect_ratio != aspect_ratio:
                continue
            if duration <= profile.max_duration:
                candidates.append(name)

        return candidates

    def get_subtitle_style(self, platform: str) -> str:
        """Platform için önerilen altyazı stilini döndürür."""
        profile = self.get_profile(platform)
        return profile.recommended_subtitle_style if profile else "classic"

    def get_max_subtitle_chars(self, platform: str) -> int:
        """Platform için maksimum altyazı karakter sayısını döndürür."""
        profile = self.get_profile(platform)
        return profile.max_subtitle_chars if profile else 100


# Singleton
platform_export = PlatformExportManager()
