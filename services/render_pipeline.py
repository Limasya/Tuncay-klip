"""
FFmpeg render pipeline - ClipSpec'i uygulayan render motoru.
Filter graph oluşturucu ve FFmpeg subprocess yöneticisi.
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

    async def render(self, spec: ClipSpec, output_path: Optional[str] = None) -> Optional[str]:
        """
        ClipSpec'i render eder. Tek klip veya montaj.
        """
        if spec.clips:
            return await self.render_montage(MontageSpec(
                clips=[spec] + spec.clips,
                transition=spec.transition_between,
                output_path=output_path or str(EXPORTS_DIR / "montage.mp4"),
            ))

        if not output_path:
            output_path = str(EXPORTS_DIR / f"render_{Path(spec.source_path).stem}.mp4")

        # 1. FFmpeg filter graph oluştur
        video_filters, audio_filters = self._build_filter_graph(spec)

        # 2. FFmpeg komutunu oluştur
        cmd = self._build_command(spec, video_filters, audio_filters, output_path)

        # 3. Çalıştır
        result = await self._run_ffmpeg(cmd, output_path)

        # 4. Thumbnail üret
        if spec.thumbnail.auto and result:
            await self._generate_thumbnail(spec, output_path)

        # 5. Geçici dosyaları temizle
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

    # --- FFmpeg Komut Oluşturucu ---

    def _build_command(
        self,
        spec: ClipSpec,
        video_filters: List[str],
        audio_filters: List[str],
        output_path: str,
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

        # Codec
        cmd.extend(["-c:v", "libx264", "-preset", "fast"])
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
