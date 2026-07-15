"""
FFmpeg render pipeline - ClipSpec'i uygulayan render motoru.
Filter graph oluşturucu ve FFmpeg subprocess yöneticisi.
Gelişmiş altyazı, efekt, platform profilleri, ses miksajı, QC entegrasyonu.
Beat-sync, word-highlight, sticker, lower-third, end-screen, split-screen,
emotion-arc, scene-detection entegrasyonu.
"""
import asyncio
import json
import logging
import shlex
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from services.edit_spec import (
    ClipSpec, MontageSpec, TimeRange, SubtitleEntry, SpeedSegment,
    AudioTrack, Watermark, ColorGrading, VisualEffect, ThumbnailSpec,
    Transition, TransitionType, SpeedEffect, SubtitleStyle, ColorPreset,
    AspectRatio,
    BeatSyncConfig, WordHighlightConfig, StickerOverlayConfig,
    LowerThirdConfig, EndScreenConfig, SplitScreenConfig,
    EmotionArcConfig, SceneDetectionConfig,
)

logger = logging.getLogger(__name__)

EXPORTS_DIR = Path("data/exports")
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

TEMP_DIR = Path("data/temp")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Color preset FFmpeg eq değerleri
COLOR_PRESET_EQ = {
    ColorPreset.VIBRANT: {"contrast": 1.1, "saturation": 1.3, "brightness": 0.02},
    ColorPreset.WARM: {"contrast": 1.05, "saturation": 1.1, "brightness": 0.03,
                        "temperature": 0.2},
    ColorPreset.COOL: {"contrast": 1.05, "saturation": 0.9, "brightness": -0.02,
                        "temperature": -0.3},
    ColorPreset.CINEMATIC: {"contrast": 1.2, "saturation": 0.85, "brightness": -0.05,
                             "gamma": 0.95},
    ColorPreset.VINTAGE: {"contrast": 1.1, "saturation": 0.7, "brightness": 0.02,
                           "gamma": 1.1},
    ColorPreset.HIGH_CONTRAST: {"contrast": 1.4, "saturation": 0.9, "brightness": -0.03},
    ColorPreset.DESATURATED: {"contrast": 1.1, "saturation": 0.4, "brightness": 0.0},
}

# Xfade mapping
TRANSITION_MAP = {
    TransitionType.FADE: "fade",
    TransitionType.DISSOLVE: "dissolve",
    TransitionType.WIPE_LEFT: "wipeleft",
    TransitionType.WIPE_RIGHT: "wiperight",
    TransitionType.WIPE_UP: "wipeup",
    TransitionType.WIPE_DOWN: "wipedown",
    TransitionType.SLIDE_LEFT: "slideleft",
    TransitionType.SLIDE_RIGHT: "slideright",
    TransitionType.ZOOM_IN: "smoothup",
    TransitionType.ZOOM_OUT: "smoothdown",
    TransitionType.FADE_BLACK: "fadeblack",
    TransitionType.FADE_WHITE: "fadewhite",
}


class RenderPipeline:
    """
    ClipSpec'i FFmpeg filter graph'a derleyip çalıştıran render motoru.
    """

    def __init__(self):
        self._temp_files: List[str] = []

    async def render(self, spec: ClipSpec, output_path: Optional[str] = None,
                     run_qc: bool = True, platform: Optional[str] = None) -> Optional[str]:
        """
        ClipSpec'i render eder. Tek klip veya montaj.
        Geliştirilmiş: altyazı burn-in, QC kontrol, platform optimizasyonu,
        beat-sync, word-highlight, sticker, lower-third, end-screen, split-screen,
        emotion-arc, scene-detection.
        """
        if spec.clips:
            return await self.render_montage(MontageSpec(
                clips=[spec] + spec.clips,
                transition=spec.transition_between,
                output_path=output_path or str(EXPORTS_DIR / "montage.mp4"),
            ))

        # Split screen ise ayrı render
        if spec.split_screen.enabled and spec.split_screen.clip_paths:
            return await self.render_split_screen(spec, output_path)

        if not output_path:
            output_path = str(EXPORTS_DIR / f"render_{Path(spec.source_path).stem}.mp4")

        # 1. FFmpeg filter graph oluştur
        video_filters, audio_filters = self._build_filter_graph(spec)

        # 2. FFmpeg komutunu oluştur
        cmd = self._build_command(spec, video_filters, audio_filters, output_path,
                                  platform=platform)

        # 3. Çalıştır
        result = await self._run_ffmpeg(cmd, output_path)

        # 4. Altyazı burn-in (varsa)
        if result and spec.subtitles:
            result = await self._burn_subtitles(spec, result)

        # 5. Thumbnail üret
        if spec.thumbnail.auto and result:
            result = await self._generate_smart_thumbnail(spec, result)

        # 6. Word highlight (karaoke) ASS burn-in
        if result and spec.word_highlight.enabled and spec.word_highlight.words:
            result = await self._burn_word_highlight(spec, result)

        # 7. Post-render QC
        if result and run_qc:
            from services.quality_control import quality_control
            qc_report = await quality_control.run_qc(result)
            if not qc_report.passed:
                logger.warning("QC başarısız: %s", qc_report.summary())
            else:
                logger.info("QC başarılı: %s", qc_report.summary())

        # 8. Geçici dosyaları temizle
        self._cleanup_temp()

        return result

    async def render_montage(self, spec: MontageSpec) -> Optional[str]:
        """
        Çoklu klibi montaj olarak render eder.
        Geçiş efektleri, arka plan müziği ile.
        """
        if not spec.clips:
            return None

        if len(spec.clips) == 1:
            return await self.render(spec.clips[0], spec.output_path)

        # 1. Her klibi ayrı ayrı render et (temp)
        rendered_paths = []
        for i, clip_spec in enumerate(spec.clips):
            temp_path = str(TEMP_DIR / f"clip_{i:03d}.mp4")
            result = await self.render(clip_spec, temp_path)
            if result:
                rendered_paths.append(result)

        if not rendered_paths:
            return None

        if len(rendered_paths) == 1:
            return rendered_paths[0]

        # 2. Klipleri birleştir (xfade ile)
        merged = await self._merge_clips_with_transitions(
            rendered_paths, spec.transition, spec.output_path
        )

        # 3. Arka plan müziği ekle
        if merged and spec.background_music:
            merged = await self._add_background_music(merged, spec.background_music)

        return merged

    # --- Filter Graph Oluşturucu ---

    def _build_filter_graph(
        self, spec: ClipSpec
    ) -> Tuple[List[str], List[str]]:
        """
        ClipSpec'den FFmpeg video ve audio filter zincirleri üretir.
        Returns: (video_filters, audio_filters)
        """
        video_filters = []
        audio_filters = []

        # === VIDEO FILTERS ===

        # 1. Aspect ratio + scale
        video_filters.append(self._build_scale_filter(spec))

        # 2. Speed (setpts)
        if spec.speed_segments:
            pts_filter = self._build_speed_filter(spec.speed_segments)
            if pts_filter:
                video_filters.append(pts_filter)

        # 3. Color grading
        cg = spec.color_grading
        eq_parts = []
        if cg.preset != ColorPreset.NONE:
            preset_eq = COLOR_PRESET_EQ.get(cg.preset, {})
            cg = cg.copy(update={
                "brightness": cg.brightness + preset_eq.get("brightness", 0),
                "contrast": cg.contrast * preset_eq.get("contrast", 1),
                "saturation": cg.saturation * preset_eq.get("saturation", 1),
                "gamma": cg.gamma * preset_eq.get("gamma", 1),
            })

        if cg.brightness != 0:
            eq_parts.append(f"brightness={cg.brightness:.3f}")
        if cg.contrast != 1.0:
            eq_parts.append(f"contrast={cg.contrast:.3f}")
        if cg.saturation != 1.0:
            eq_parts.append(f"saturation={cg.saturation:.3f}")
        if cg.gamma != 1.0:
            eq_parts.append(f"gamma={cg.gamma:.3f}")

        if eq_parts:
            video_filters.append(f"eq={':'.join(eq_parts)}")

        # 4. Visual effects
        fx = spec.effects
        if fx.vignette > 0:
            video_filters.append(
                f"vignette=PI/{4 - fx.vignette * 2}"
            )
        if fx.glow > 0:
            video_filters.append(
                f"unsharp=3:3:{fx.glow * 2}:3:3:0"
            )
        if fx.sharpen > 0:
            video_filters.append(
                f"unsharp=5:5:{fx.sharpen}:5:5:0"
            )
        if fx.film_grain > 0:
            video_filters.append(
                f"noise=alls={int(fx.film_grain * 50)}:allf=t"
            )
        if fx.chromatic_aberration > 0:
            video_filters.append(self._build_chromatic_aberration(fx.chromatic_aberration))
        if fx.shake > 0:
            video_filters.append(self._build_shake_filter(fx.shake))

        # 5. Watermark (drawtext)
        if spec.watermark and spec.watermark.text:
            video_filters.append(self._build_watermark_filter(spec.watermark))

        # 6. Emotion arc efektleri
        if spec.emotion_arc.enabled and spec.emotion_arc.segments:
            emotion_filters = self._build_emotion_arc_filters(spec.emotion_arc)
            if emotion_filters:
                video_filters.extend(emotion_filters)

        # 7. Beat-sync efektleri
        if spec.beat_sync.enabled:
            beat_filters = self._build_beat_sync_filters(spec.beat_sync)
            if beat_filters:
                video_filters.extend(beat_filters)

        # 8. Sticker/emoji overlay
        if spec.stickers.enabled:
            sticker_filter = self._build_sticker_filters(spec.stickers)
            if sticker_filter:
                video_filters.append(sticker_filter)

        # 9. Lower third grafikleri
        if spec.lower_thirds.enabled:
            lt_filters = self._build_lower_third_filters(spec.lower_thirds)
            if lt_filters:
                video_filters.extend(lt_filters)

        # 10. End screen overlay
        if spec.end_screen.enabled:
            end_filter = self._build_end_screen_filter(spec.end_screen)
            if end_filter:
                video_filters.append(end_filter)

        # === AUDIO FILTERS ===

        # 1. Volume ayarı
        if spec.music_volume != 1.0:
            audio_filters.append(f"volume={spec.music_volume}")

        # 2. Speed (atempo)
        if spec.speed_segments:
            atempo = self._build_atempo_filter(spec.speed_segments)
            if atempo:
                audio_filters.append(atempo)

        # 3. Fade in/out
        if spec.watermark:
            pass  # Watermark ses fade gerektirmez

        return video_filters, audio_filters

    def _build_scale_filter(self, spec: ClipSpec) -> str:
        """Aspect ratio ve çözünürlük scale filtresi."""
        ratios = {
            AspectRatio.PORTRAIT_9_16: (1080, 1920),
            AspectRatio.LANDSCAPE_16_9: (1920, 1080),
            AspectRatio.SQUARE_1_1: (1080, 1080),
            AspectRatio.PORTRAIT_4_5: (1080, 1350),
        }
        w, h = ratios.get(spec.aspect_ratio, (1080, 1920))

        if spec.aspect_ratio == AspectRatio.PORTRAIT_9_16:
            return (
                f"crop=ih*9/16:ih,"
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
            )
        elif spec.aspect_ratio == AspectRatio.SQUARE_1_1:
            return (
                f"crop='min(iw,ih)':'min(iw,ih)',"
                f"scale={w}:{h}"
            )
        elif spec.aspect_ratio == AspectRatio.PORTRAIT_4_5:
            return (
                f"crop=ih*4/5:ih,"
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
            )
        else:
            return (
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
            )

    def _build_speed_filter(self, segments: List[SpeedSegment]) -> Optional[str]:
        """Hız segmentlerinden setpts filtresi üretir."""
        if not segments:
            return None

        seg = segments[0]
        if seg.effect == SpeedEffect.FREEZE_FRAME:
            return f"select='between(t,{seg.time_range.start},{seg.time_range.end})',setpts=PTS-STARTPTS"
        elif seg.speed != 1.0:
            pts_factor = 1.0 / seg.speed
            return f"setpts={pts_factor:.4f}*PTS"

        return None

    def _build_atempo_filter(self, segments: List[SpeedSegment]) -> Optional[str]:
        """Hız segmentlerinden atempo filtresi üretir."""
        if not segments:
            return None

        seg = segments[0]
        if seg.speed != 1.0:
            # atempo 0.5-2.0 aralığında çalışır, zincirleme gerekebilir
            speed = max(0.5, min(2.0, seg.speed))
            return f"atempo={speed:.4f}"

        return None

    def _build_chromatic_aberration(self, intensity: float) -> str:
        """Chromatic aberration efekti (basitleştirilmiş)."""
        offset = int(intensity * 5)
        return (
            f"rgbashift=rh={offset}:bh=-{offset}"
        )

    def _build_shake_filter(self, intensity: float) -> str:
        """Camera shake efekti (basitleştirilmiş)."""
        amp = int(intensity * 8)
        return (
            f"crop=iw-{amp*2}:ih-{amp*2}:{amp}+random(1)*{amp}:{amp}+random(2)*{amp},"
            f"scale=iw+{amp*2}:ih+{amp*2}"
        )

    def _build_watermark_filter(self, wm: Watermark) -> str:
        """Drawtext watermark filtresi."""
        pos_map = {
            "top_left": "x=20:y=20",
            "top_right": "x=w-tw-20:y=20",
            "bottom_left": "x=20:y=h-th-20",
            "bottom_right": "x=w-tw-20:y=h-th-20",
            "center": "x=(w-tw)/2:y=(h-th)/2",
        }
        pos = pos_map.get(wm.position, "x=w-tw-20:y=h-th-20")
        text = wm.text or ""
        opacity = wm.opacity

        return (
            f"drawtext=text='{text}':"
            f"fontsize=20:fontcolor=white@{opacity:.2f}:"
            f"borderw=1:bordercolor=black@0.5:"
            f"{pos}"
        )

    # --- Beat-Sync Filtreleri ---

    def _build_beat_sync_filters(self, config: BeatSyncConfig) -> List[str]:
        """Beat-sync efektlerinden FFmpeg filter listesi üretir."""
        from services.beat_sync import beat_sync
        import asyncio

        filters = []

        # Beat grid oluştur (sync wrapper)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Zaten bir event loop çalışıyorsa senkron workaround
                beat_grid = None
            else:
                beat_grid = loop.run_until_complete(
                    beat_sync.detect_beats(config.audio_path or "", config.bpm or 0.8)
                )
        except Exception:
            beat_grid = None

        if not beat_grid or not beat_grid.beats:
            return filters

        # BPM override
        if config.bpm:
            from services.beat_sync import BeatGrid, BeatInfo
            interval = 60.0 / config.bpm
            beats = []
            t = 0.0
            beat_num = 0
            while t < beat_grid.duration:
                is_downbeat = (beat_num % 4 == 0)
                beats.append(BeatInfo(
                    time=t,
                    strength=1.0 if is_downbeat else 0.6,
                    bpm=config.bpm,
                    beat_number=beat_num % 4,
                    is_downbeat=is_downbeat,
                ))
                t += interval
                beat_num += 1
            beat_grid = BeatGrid(
                bpm=config.bpm, beats=beats,
                total_bars=beat_num // 4,
                time_signature="4/4",
                duration=beat_grid.duration,
            )

        # Zoom on beat
        if config.zoom_on_beat:
            zoom_filter = beat_sync.generate_beat_zoom_filter(
                beat_grid, config.zoom_level, config.downbeats_only
            )
            if zoom_filter and zoom_filter != "null":
                filters.append(zoom_filter)

        # Flash on beat
        if config.flash_on_beat:
            flash_filter = beat_sync.generate_beat_flash_filter(
                beat_grid, config.flash_color, config.flash_intensity
            )
            if flash_filter and flash_filter != "null":
                filters.append(flash_filter)

        # Shake on beat
        if config.shake_on_beat:
            shake_filter = beat_sync.generate_beat_shake_filter(
                beat_grid, config.shake_intensity
            )
            if shake_filter and shake_filter != "null":
                filters.append(shake_filter)

        # Speed variation
        if config.speed_variation:
            speed_filter = beat_sync.generate_beat_speed_filter(
                beat_grid, config.slow_on_beat, config.fast_between
            )
            if speed_filter and speed_filter != "null":
                filters.append(speed_filter)

        return filters

    # --- Emotion Arc Filtreleri ---

    def _build_emotion_arc_filters(self, config: EmotionArcConfig) -> List[str]:
        """Emotion arc efektlerinden FFmpeg filter listesi üretir."""
        from services.emotion_arc import emotion_arc, EmotionArc, EmotionPoint

        filters = []

        # EmotionArc oluştur
        segments = []
        for seg in config.segments:
            segments.append({
                "start": seg.start,
                "end": seg.end,
                "emotion": seg.emotion,
                "intensity": seg.intensity,
            })

        if not segments:
            return filters

        # Süre bilgisi (varsayılan 10s)
        total_duration = max(s["end"] for s in segments) if segments else 10.0
        arc = emotion_arc.build_emotion_arc(segments, total_duration)

        if config.apply_color:
            color_filter = emotion_arc.generate_emotion_color_filter(arc)
            if color_filter and color_filter != "null":
                filters.append(color_filter)

        if config.apply_speed:
            speed_filter = emotion_arc.generate_emotion_speed_filter(arc)
            if speed_filter and speed_filter != "null":
                filters.append(speed_filter)

        if config.apply_vignette:
            vig_filter = emotion_arc.generate_emotion_vignette_filter(arc)
            if vig_filter and vig_filter != "null":
                filters.append(vig_filter)

        return filters

    # --- Sticker Filtreleri ---

    def _build_sticker_filters(self, config: StickerOverlayConfig) -> str:
        """Sticker overlay'lerinden FFmpeg filter string'i üretir."""
        from services.sticker_engine import sticker_engine, StickerDef

        parts = []

        # Tekil sticker'lar
        if config.stickers:
            sticker_defs = []
            for s in config.stickers:
                sticker_defs.append(StickerDef(
                    emoji=s.emoji, x=s.x, y=s.y,
                    start=s.start, duration=s.duration,
                    scale=s.scale, animation=s.animation,
                    opacity=s.opacity,
                ))
            sticker_filter = sticker_engine.generate_sticker_filter(sticker_defs)
            if sticker_filter and sticker_filter != "null":
                parts.append(sticker_filter)

        # Reaksiyon overlay
        if config.reaction_type:
            reaction_filter = sticker_engine.generate_reaction_overlay(
                config.reaction_type,
                config.reaction_start,
                config.reaction_duration,
            )
            if reaction_filter and reaction_filter != "null":
                parts.append(reaction_filter)

        # Emoji rain
        if config.emoji_rain:
            rain_filter = sticker_engine.generate_emoji_rain(
                config.emoji_rain_emoji,
                config.emoji_rain_start,
                config.emoji_rain_duration,
            )
            if rain_filter and rain_filter != "null":
                parts.append(rain_filter)

        # Confetti
        if config.confetti:
            confetti_filter = sticker_engine.generate_confetti(
                config.confetti_start,
                config.confetti_duration,
            )
            if confetti_filter and confetti_filter != "null":
                parts.append(confetti_filter)

        return ",".join(parts) if parts else "null"

    # --- Lower Third Filtreleri ---

    def _build_lower_third_filters(self, config: LowerThirdConfig) -> List[str]:
        """Lower third grafiklerinden FFmpeg filter listesi üretir."""
        from services.lower_third import lower_third

        filters = []

        for entry in config.entries:
            if entry.animated:
                lt_filter = lower_third.generate_animated_lower_third(
                    name=entry.name,
                    title=entry.title,
                    style=entry.style,
                    start_time=entry.start_time,
                    duration=entry.duration,
                )
            else:
                lt_filter = lower_third.generate_lower_third(
                    name=entry.name,
                    title=entry.title,
                    style=entry.style,
                    start_time=entry.start_time,
                    duration=entry.duration,
                    position=entry.position,
                )
            if lt_filter:
                filters.append(lt_filter)

        # Skor tablosu
        if config.scoreboard:
            sb_filter = lower_third.generate_scoreboard(
                config.scoreboard_player1,
                config.scoreboard_score1,
                config.scoreboard_player2,
                config.scoreboard_score2,
            )
            if sb_filter:
                filters.append(sb_filter)

        # İlerleme çubuğu
        if config.progress_bar:
            pb_filter = lower_third.generate_progress_bar(
                0.5,  # Varsayılan başlangıç
                config.progress_bar_color,
            )
            if pb_filter:
                filters.append(pb_filter)

        return filters

    # --- End Screen Filtresi ---

    def _build_end_screen_filter(self, config: EndScreenConfig) -> str:
        """End screen overlay'inden FFmpeg filter string'i üretir."""
        from services.end_screen import end_screen

        parts = []

        # End screen template
        es_filter = end_screen.generate_end_screen(
            template=config.template,
            custom_text=config.custom_text,
        )
        if es_filter and es_filter != "null":
            parts.append(es_filter)

        # CTA overlay
        if config.call_to_action:
            cta_filter = end_screen.generate_call_to_action(
                config.call_to_action,
                config.cta_position,
            )
            if cta_filter:
                parts.append(cta_filter)

        return ",".join(parts) if parts else "null"

    # --- Split Screen Render ---

    async def render_split_screen(
        self,
        spec: ClipSpec,
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        Split screen render'i.
        Çoklu giriş videosunu xstack ile birleştirir.
        """
        from services.split_screen import split_screen

        if not spec.split_screen.clip_paths:
            return await self.render(spec, output_path)

        if not output_path:
            output_path = str(EXPORTS_DIR / f"split_{Path(spec.source_path).stem}.mp4")

        # Filter_complex oluştur
        filter_complex = split_screen.generate_split_filter(
            spec.split_screen.layout,
            gap=spec.split_screen.gap,
        )

        # FFmpeg komutu (çoklu giriş)
        cmd = ["ffmpeg", "-y"]
        for path in spec.split_screen.clip_paths:
            cmd.extend(["-i", path])

        cmd.extend([
            "-filter_complex", filter_complex,
            "-c:v", "libx264", "-preset", "fast",
            "-crf", str(spec.crf),
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            output_path,
        ])

        result = await self._run_ffmpeg(cmd, output_path)
        self._cleanup_temp()
        return result

    # --- FFmpeg Komut Oluşturucu ---

    def _build_command(
        self,
        spec: ClipSpec,
        video_filters: List[str],
        audio_filters: List[str],
        output_path: str,
        platform: Optional[str] = None,
    ) -> List[str]:
        """FFmpeg komut argümanlarını oluşturur."""
        cmd = ["ffmpeg", "-y"]

        # Input
        cmd.extend(["-i", spec.source_path])

        # Video filter chain
        if video_filters:
            vf = ",".join(video_filters)
            cmd.extend(["-vf", vf])

        # Audio filter chain
        if audio_filters:
            af = ",".join(audio_filters)
            cmd.extend(["-af", af])

        # Codec (platform bazlı preset)
        preset_map = {
            "tiktok": "veryfast",
            "youtube": "medium",
            "instagram": "fast",
            "kick": "fast",
            "twitter": "veryfast",
        }
        preset = preset_map.get(platform, "fast") if platform else "fast"

        cmd.extend(["-c:v", "libx264", "-preset", preset])
        cmd.extend(["-crf", str(spec.crf)])
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])

        # Container flags
        if spec.output_format == "mp4":
            cmd.extend(["-movflags", "+faststart"])

        # Output
        cmd.append(output_path)

        return cmd

    # --- Montaj Birleştirme ---

    async def _merge_clips_with_transitions(
        self,
        clip_paths: List[str],
        transition: Transition,
        output_path: str,
    ) -> Optional[str]:
        """
        Klipleri xfade ile birleştirir.
        2+ clip için zincirleme xfade kullanır.
        """
        if len(clip_paths) < 2:
            return clip_paths[0] if clip_paths else None

        # Her seferinde 2 klibi birleştir
        current = clip_paths[0]
        for i in range(1, len(clip_paths)):
            next_clip = clip_paths[i]
            temp_out = str(TEMP_DIR / f"merged_{i:03d}.mp4")

            xfade_type = TRANSITION_MAP.get(transition.type, "fade")
            dur = transition.duration

            # Input sürelerini al
            dur_current = await self._get_duration(current)
            dur_next = await self._get_duration(next_clip)
            offset = max(0, dur_current - dur)

            cmd = [
                "ffmpeg", "-y",
                "-i", current,
                "-i", next_clip,
                "-filter_complex",
                (
                    f"[0:v][1:v]xfade=transition={xfade_type}:"
                    f"duration={dur}:offset={offset:.3f}[v];"
                    f"[0:a][1:a]acrossfade=d={dur}[a]"
                ),
                "-map", "[v]",
                "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac",
                temp_out,
            ]

            result = await self._run_ffmpeg(cmd, temp_out)
            if result:
                current = temp_out
            else:
                logger.warning("xfade başarısız, basit concat'a düşülüyor")
                return await self._fallback_concat(clip_paths, output_path)

        # Sonucu hedefe kopyala
        if current != output_path:
            import shutil
            shutil.copy2(current, output_path)

        return output_path

    async def _fallback_concat(
        self, clip_paths: List[str], output_path: str
    ) -> Optional[str]:
        """xfade başarısız olursa basit concat ile birleştirir."""
        list_file = str(TEMP_DIR / "concat_list.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for path in clip_paths:
                abs_path = str(Path(path).resolve())
                f.write(f"file '{abs_path}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path)

    async def _add_background_music(
        self, video_path: str, music: AudioTrack
    ) -> Optional[str]:
        """Videoya arka plan müziği ekler (ducking ile)."""
        output_path = str(
            EXPORTS_DIR / f"{Path(video_path).stem}_music.mp4"
        )

        # Ducking filter
        if music.duck:
            # sidechaincompress ile ducking
            af = (
                f"[1:a]volume={music.volume},afade=t=in:d={music.fade_in},"
                f"afade=t=out:st=9999:d={music.fade_out}[bg];"
                f"[0:a][bg]amix=inputs=2:duration=first:dropout_transition=3,"
                f"sidechaincompress=threshold=0.02:ratio=4:attack=200:release=1000[out]"
            )
        else:
            af = (
                f"[1:a]volume={music.volume},afade=t=in:d={music.fade_in}[bg];"
                f"[0:a][bg]amix=inputs=2:duration=first[out]"
            )

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", music.path,
            "-filter_complex",
            f"[0:v]copy[v];{af}",
            "-map", "[v]",
            "-map", "[out]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path)

    async def _generate_thumbnail(self, spec: ClipSpec, video_path: str):
        """Klip için otomatik thumbnail üretir."""
        thumb_path = str(
            EXPORTS_DIR / f"{Path(spec.source_path).stem}_thumb.jpg"
        )

        # İlk kareyi al (veya belirli bir zaman)
        time_point = spec.thumbnail.time_point or 0.5

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", str(time_point),
            "-vframes", "1",
            "-q:v", "2",
            thumb_path,
        ]

        await self._run_ffmpeg(cmd, thumb_path)

    # --- Yardımcılar ---

    async def _get_duration(self, path: str) -> float:
        """Video dosyasının süresini alır."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            data = json.loads(stdout.decode())
            return float(data.get("format", {}).get("duration", 10.0))
        except Exception:
            return 10.0

    async def _run_ffmpeg(
        self, cmd: List[str], output_path: str
    ) -> Optional[str]:
        """FFmpeg komutunu çalıştırır."""
        try:
            logger.debug("FFmpeg: %s", " ".join(cmd[:10]) + "...")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=600
            )

            if proc.returncode == 0:
                logger.info("Render başarılı: %s", output_path)
                return output_path
            else:
                err = stderr.decode()[:800]
                logger.error("FFmpeg hatası (kod %d): %s", proc.returncode, err)
                return None

        except asyncio.TimeoutError:
            logger.error("FFmpeg zaman aşımı")
            return None
        except Exception as e:
            logger.error("FFmpeg çalıştırma hatası: %s", e)
            return None

    # --- Gelişmiş Yardımcılar ---

    async def _burn_subtitles(self, spec: ClipSpec, video_path: str) -> Optional[str]:
        """
        Altyazılari videoya gömer (ASS formatı ile).
        """
        from services.advanced_subtitle import advanced_subtitle

        # ASS içeriği üret
        ass_content = advanced_subtitle.generate_ass(
            entries=[
                {"text": s.text, "start": s.start, "end": s.end}
                for s in spec.subtitles
            ],
            style_name=spec.subtitles[0].style if spec.subtitles else "classic",
        )

        # ASS dosyasını kaydet
        ass_path = str(TEMP_DIR / f"{Path(video_path).stem}.ass")
        advanced_subtitle.save_ass(ass_content, ass_path)

        # Burn-in
        output_path = str(
            EXPORTS_DIR / f"{Path(video_path).stem}_sub.mp4"
        )
        result = await advanced_subtitle.burn_ass_subtitles(
            video_path, ass_path, output_path
        )

        return result if result else video_path

    async def _generate_smart_thumbnail(self, spec: ClipSpec, video_path: str) -> Optional[str]:
        """
        Akıllı thumbnail üretir (yüz algılama, platform optimizasyonu).
        """
        from services.thumbnail_engine import thumbnail_engine

        output_path = str(
            EXPORTS_DIR / f"{Path(spec.source_path).stem}_thumb.jpg"
        )

        result = await thumbnail_engine.generate_smart_thumbnail(
            video_path=video_path,
            output_path=output_path,
            time_point=spec.thumbnail.time_point,
            add_title=spec.thumbnail.add_title,
            title_text=spec.thumbnail.title_text or spec.category,
            title_style=spec.thumbnail.style,
        )

        return result

    async def _burn_word_highlight(self, spec: ClipSpec, video_path: str) -> Optional[str]:
        """
        Word highlight (karaoke) ASS dosyasını videoya gömer.
        """
        from services.word_highlight import word_highlight, WordTiming

        # Word timing listesini oluştur
        words = []
        for w in spec.word_highlight.words:
            words.append(WordTiming(
                word=w.get("word", ""),
                start=w.get("start", 0.0),
                end=w.get("end", 0.0),
                confidence=w.get("confidence", 1.0),
            ))

        # ASS içeriği üret
        ass_content = word_highlight.generate_karaoke_ass(
            words=words,
            palette=spec.word_highlight.palette,
            font_size=spec.word_highlight.font_size,
            max_chars_per_line=spec.word_highlight.max_chars_per_line,
            position=spec.word_highlight.position,
            outline=spec.word_highlight.outline,
            shadow=spec.word_highlight.shadow,
        )

        # ASS dosyasını kaydet
        ass_path = str(TEMP_DIR / f"{Path(video_path).stem}_karaoke.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        # Burn-in
        output_path = str(
            EXPORTS_DIR / f"{Path(video_path).stem}_kh.mp4"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"ass={ass_path}",
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "copy",
            output_path,
        ]

        result = await self._run_ffmpeg(cmd, output_path)
        return result if result else video_path

    async def render_for_platform(
        self,
        spec: ClipSpec,
        platform: str,
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        Belirli bir platform için render eder.
        Platform profilini uygular.
        """
        from services.platform_profiles import platform_export

        profile = platform_export.get_profile(platform)
        if not profile:
            logger.warning("Bilinmeyen platform: %s", platform)
            return await self.render(spec, output_path)

        # Platform-specific aspect ratio ile render et
        from services.edit_spec import AspectRatio
        try:
            ar = AspectRatio(profile.aspect_ratio)
        except ValueError:
            ar = spec.aspect_ratio

        spec = spec.copy(update={"aspect_ratio": ar, "crf": profile.crf})

        return await self.render(
            spec, output_path, run_qc=True, platform=platform
        )

    async def render_multi_platform(
        self,
        spec: ClipSpec,
        platforms: List[str],
    ) -> Dict[str, Optional[str]]:
        """
        Birden fazla platform için ayrı ayrı render eder.
        """
        results = {}
        for platform in platforms:
            output_path = str(
                EXPORTS_DIR / f"{Path(spec.source_path).stem}_{platform}.mp4"
            )
            result = await self.render_for_platform(spec, platform, output_path)
            results[platform] = result

        return results

    def _cleanup_temp(self):
        """Geçici dosyaları temizler."""
        for f in self._temp_files:
            try:
                Path(f).unlink(missing_ok=True)
            except Exception:
                pass
        self._temp_files.clear()


# Singleton
render_pipeline = RenderPipeline()
