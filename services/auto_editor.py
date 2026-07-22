"""
Auto-Edit Servisi — TikTok/Instagram Reels optimize edilmis klipler uretir.
──────────────────────────────────────────────────────────────
Izleyici kliplerini indirir, duzenler, sunar:
  1. Kick CDN'den clip video'sunu indir (sadece edit icin)
  2. 9:16 dikey formata kirp (1080x1920)
  3. Optimal sureye kes (15-45s, hook analizine gore)
  4. Hook text overlay ekle (ilk 3 saniye)
  5. Karaoke tarzi kelime kelime altyazi uret (Whisper)
  6. Guvenli bolgede watermark ekle
  7. Thumbnail uret
  8. Platform-specific export (TikTok / Instagram Reels)

Indirme: Sadece edit yapilmasi gereken klip'ler indirilir.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("auto_editor")

EDITED_DIR = Path("data/edited_clips")
EDITED_DIR.mkdir(parents=True, exist_ok=True)

# ── Platform safe-zone constants ────────────────────────────────
# TikTok: top ~15% reserved for status bar, bottom ~35% for UI
# Instagram Reels: top ~12%, bottom ~30% for UI
SAFE_ZONES = {
    "tiktok": {
        "top_pct": 0.15,
        "bottom_pct": 0.35,
        "center_top_pct": 0.25,
        "center_bottom_pct": 0.65,
    },
    "instagram_reels": {
        "top_pct": 0.12,
        "bottom_pct": 0.30,
        "center_top_pct": 0.22,
        "center_bottom_pct": 0.70,
    },
    "youtube_shorts": {
        "top_pct": 0.10,
        "bottom_pct": 0.25,
        "center_top_pct": 0.20,
        "center_bottom_pct": 0.75,
    },
    "x": {
        "top_pct": 0.05,
        "bottom_pct": 0.10,
        "center_top_pct": 0.15,
        "center_bottom_pct": 0.85,
    },
}

# Target vertical resolution
VERT_WIDTH = 1080
VERT_HEIGHT = 1920


class AutoEditor:
    """
    TikTok/Instagram Reels icin optimize edilmis otomatik video edit servisi.
    FFmpeg tabanli — hafif, hizli edit.
    """

    def __init__(self, watermark_text: str = "Tuncay-Klip"):
        self.watermark_text = watermark_text
        self._edit_queue: list[dict] = []
        self._results: list[dict] = []
        self._is_processing = False
        self._cached_encoder: str | None = None

    def get_best_encoder(self) -> str:
        """Donanım ivmelendirmeli en hızlı FFmpeg video kodlayıcısını döndürür (NVENC/QSV/AMF/libx264)."""
        if self._cached_encoder:
            return self._cached_encoder

        encoder = "libx264"
        try:
            res = subprocess.run(["ffmpeg", "-encoders"], capture_output=True, text=True, timeout=3)
            out = res.stdout.lower()
            if "h264_nvenc" in out:
                encoder = "h264_nvenc"
            elif "h264_qsv" in out:
                encoder = "h264_qsv"
            elif "h264_amf" in out:
                encoder = "h264_amf"
        except Exception:
            pass

        self._cached_encoder = encoder
        logger.info("AutoEditor hardware encoder: %s", encoder)
        return encoder

    # ── Main Pipeline ────────────────────────────────────────────

    def generate_edit_spec(
        self,
        source_path: str,
        analysis: dict | None = None,
        category: str = "other",
        aspect_ratio="9:16",
        resolution: str = "1080p",
        custom_overrides: dict | None = None,
    ):
        """Edit spec oluşturur (analiz sinyallerine göre)."""
        from types import SimpleNamespace as _NS
        from services.edit_spec import AspectRatio as _AR

        merged_analysis = dict(analysis or {})
        if custom_overrides:
            for k, v in custom_overrides.items():
                if v is not None:
                    merged_analysis[k] = v

        ar_obj = _AR(str(aspect_ratio)) if str(aspect_ratio) in [a.value for a in _AR] else _AR.PORTRAIT_9_16
        score = float(merged_analysis.get("composite_score", 0.5))
        return _NS(
            version="2.0-stub",
            source_path=source_path,
            aspect_ratio=ar_obj,
            resolution=resolution,
            color_grading=_NS(preset=_NS(value="vibrant")),
            subtitles=[_NS(style=_NS(value="modern"))],
            speed_segments=[],
            watermark=_NS(visible=True),
            audio_tracks=[],
            category=category,
            composite_score=score,
        )

    async def edit_clip(
        self,
        clip: dict[str, Any],
        platform: str = "tiktok",
        enable_viral_effects: bool = True,
        local_path: str = "",
    ) -> dict[str, Any]:
        """
        Tek bir klibi TikTok/Instagram optimize duzenleme pipeline'i ile duzenle.
        local_path verilirse download'i atla, direkt dosyadan calis.

        Pipeline:
          a. Download clip (local_path varsa atlanir)
          b. Crop to 9:16 vertical
          c. Trim to optimal duration (15-45s)
          d. Add hook text overlay (first 3s)
          e. Add animated captions (Whisper -> ASS/SRT)
          f. Add subtle watermark
          g1. Arka plan muzigi (opsiyonel)
          g2. Meme overlay (opsiyonel, viral efekt)
          g3. Ses efektleri (opsiyonel, viral efekt)
          h. Extract thumbnail
          i. Export: 1080x1920, 30fps, H.264, AAC stereo
        
        Viral efektler clip dict'inden alinir:
          clip["meme_overlays"] = [{meme_path, timestamp, duration, position, scale_pct, opacity}]
          clip["sfx_events"] = [{event_type, timestamp, volume_db}]
          clip["music_path"] = "data/music/song.mp3"
          clip["music_volume_db"] = -18.0
        
        enable_viral_effects=True ise, analiz edilmisse direkt kullanir,
        yoksa clip_analyzer'dan anlik olarak meme/SFX cikarir.
        """
        clip_id = clip.get("clip_id", "unknown")
        clip_url = clip.get("clip_url", "")
        title = clip.get("title", "untitled")
        score = clip.get("score", 0)
        hook_text = clip.get("hook_suggestion", "")
        start_offset = clip.get("start_offset", 0.0)
        duration = clip.get("duration", 30)
        hook_timestamps = clip.get("hook_timestamps", [])

        if not clip_url:
            return {"status": "error", "error": "no clip_url", "clip_id": clip_id}

        # ── Viral efektleri auto-pick (clip'te yoksa viral analiz sistemini kullan) ──
        if enable_viral_effects and not any([
            clip.get("meme_overlays"), clip.get("sfx_events"), clip.get("music_path")
        ]):
            try:
                # Önce viral LLM analizörünü dene
                from services.edit_recommendation import edit_recommendation_engine
                
                # Edit önerileri üret
                content_description = f"{title} - {clip.get('description', '')}"
                transcript = clip.get("transcript", "")
                emotions = clip.get("emotions", [])
                
                comprehensive_recommendations = await edit_recommendation_engine.generate_comprehensive_recommendations(
                    content_description=content_description,
                    video_path=clip_url,
                    video_duration=duration,
                    target_platform=platform,
                    content_category=clip.get("category", "general"),
                    transcript=transcript,
                    emotions=emotions,
                )
                
                # Edit specification'dan viral efektleri al
                edit_spec = comprehensive_recommendations.get("edit_specification", {})
                
                if not clip.get("meme_overlays"):
                    clip["meme_overlays"] = edit_spec.get("meme_overlays", [])
                if not clip.get("sfx_events"):
                    clip["sfx_events"] = edit_spec.get("sfx_events", [])
                if not clip.get("music_path"):
                    # Audio strategy'den music path al
                    audio_strategy = edit_spec.get("audio_strategy", {})
                    clip["music_path"] = audio_strategy.get("music_path", "")
                    clip["music_volume_db"] = audio_strategy.get("volume", -18.0)
                
                # Hook stratejisini güncelle
                hook_strategy = edit_spec.get("hook_strategy", {})
                if hook_strategy and not hook_text:
                    hook_text = hook_strategy.get("description", title)
                
                # Caption stratejisini güncelle
                caption_strategy = edit_spec.get("caption_strategy", {})
                if caption_strategy:
                    clip["caption_style"] = caption_strategy.get("style", "karaoke")
                
                logger.info("Viral LLM analizi uygulandı: %d meme, %d SFX, confidence: %.1f%%",
                            len(clip.get("meme_overlays", [])),
                            len(clip.get("sfx_events", [])),
                            comprehensive_recommendations.get("confidence_score", 0.0) * 100)
                
            except Exception as llm_error:
                logger.debug("Viral LLM analizi başarısız, fallback kullanılıyor: %s", llm_error)
                # Fallback: clip_analyzer kullan
                try:
                    from services.clip_analyzer import clip_analyzer as _ca
                    analysis = await _ca.analyze_clip(clip)
                    if not clip.get("meme_overlays"):
                        clip["meme_overlays"] = analysis.get("meme_overlays", [])
                    if not clip.get("sfx_events"):
                        clip["sfx_events"] = analysis.get("sfx_events", [])
                    if not clip.get("music_path"):
                        clip["music_path"] = analysis.get("music_path", "")
                    if not clip.get("music_volume_db"):
                        clip["music_volume_db"] = analysis.get("music_volume_db", -18.0)
                    logger.info("Fallback viral analizi: %d meme, %d SFX",
                                len(clip.get("meme_overlays", [])),
                                len(clip.get("sfx_events", [])))
                except Exception as fallback_error:
                    logger.debug("Fallback viral analizi de başarısız: %s", fallback_error)

        result = {
            "clip_id": clip_id,
            "original_title": title,
            "score": score,
            "platform": platform,
            "status": "processing",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        working_files: list[Path] = []

        try:
            # (a) Video indir (local_path varsa atla)
            raw_path = EDITED_DIR / f"raw_{clip_id}.mp4"
            if local_path and os.path.exists(local_path):
                shutil.copy2(local_path, str(raw_path))
                logger.info("Local dosya kullanildi: %s", local_path)
            else:
                download_ok = await self._download_clip(clip_url, str(raw_path))
                if not download_ok:
                    result["status"] = "error"
                    result["error"] = "download_failed"
                    return result
            working_files.append(raw_path)

            # (a.5) Bos/sessiz/donuk bolumleri otomatik kirp — sadece aktif kisimlari tut
            active_path = EDITED_DIR / f"active_{clip_id}.mp4"
            actual_dur = await self._auto_trim_inactive(str(raw_path), str(active_path))
            if active_path.exists() and os.path.getsize(str(active_path)) > 1024 * 100:
                working_files.append(active_path)
                duration = actual_dur
            else:
                active_path = raw_path

            # (b) 9:16 dikey formata kirp (aktif kirpilmis videodan)
            vertical_path = EDITED_DIR / f"vert_{clip_id}.mp4"
            await self._crop_to_vertical(str(active_path), str(vertical_path), duration=duration)
            working_files.append(vertical_path)

            # (c) Optimal sureye kes
            # Hook timestamp'lerinden en guclu baslangic noktasini bul
            clip_start = start_offset
            clip_duration = min(max(duration, 15), 45)  # 15-45s arasi

            if hook_timestamps:
                best_hook = max(hook_timestamps, key=lambda h: h.get("strength", 0))
                clip_start = best_hook.get("t", start_offset)
                # Hook'tan basla, 45s'e kadar
                remaining = duration - clip_start
                clip_duration = min(max(remaining, 15), 45)

            trimmed_path = EDITED_DIR / f"trimmed_{clip_id}.mp4"
            await self._trim_clip(
                str(vertical_path), str(trimmed_path),
                start=clip_start, duration=clip_duration,
            )
            working_files.append(trimmed_path)

            # (d) Hook text overlay (ilk 3 saniye)
            hooked_path = EDITED_DIR / f"hooked_{clip_id}.mp4"
            hook_display = hook_text or title
            await self._add_hook_text(
                str(trimmed_path), str(hooked_path),
                hook_display, duration=3,
            )
            working_files.append(hooked_path)

            # (e) Altyazi uret ve yak (karaoke kelime kelime)
            sub_path = EDITED_DIR / f"sub_{clip_id}.ass"
            has_subs = await self._generate_karaoke_subtitles(
                str(hooked_path), str(sub_path), platform=platform,
            )

            captioned_path = EDITED_DIR / f"captioned_{clip_id}.mp4"
            if has_subs:
                await self._burn_subtitles(
                    str(hooked_path), str(sub_path), str(captioned_path),
                    platform=platform,
                )
                working_files.append(captioned_path)
            else:
                captioned_path = hooked_path

            # (f) Watermark ekle (guvenli bolgede)
            watermark_path = EDITED_DIR / f"wm_{clip_id}.mp4"
            await self._add_watermark(
                str(captioned_path), str(watermark_path), platform=platform,
            )
            working_files.append(watermark_path)

            # (g1) Arka plan muzigi ekle (varsa)
            music_path = clip.get("music_path", "")
            has_music = bool(music_path)
            if music_path:
                music_path = str(EDITED_DIR / ".." / music_path) if not os.path.isabs(music_path) else music_path
            else:
                music_path = ""

            music_output = EDITED_DIR / f"music_{clip_id}.mp4"
            if music_path and os.path.exists(music_path):
                from services.auto_sfx import auto_sfx as _sfx
                music_ok = await _sfx.add_background_music(
                    str(watermark_path), music_path, str(music_output),
                    volume_db=clip.get("music_volume_db", -18.0),
                )
                if music_ok:
                    working_files.append(music_output)
                    has_music = True
                else:
                    music_output = watermark_path
            else:
                music_output = watermark_path

            # (g2) Meme overlay (varsa)
            meme_info = clip.get("meme_overlays", [])
            has_meme = bool(meme_info)
            meme_path = EDITED_DIR / f"memed_{clip_id}.mp4"
            if meme_info:
                from services.meme_overlay import meme_overlay as _meme
                meme_ok = await _meme.add_multiple_overlays(
                    str(music_output), meme_info, str(meme_path),
                )
                if meme_ok:
                    working_files.append(meme_path)
                    has_meme = True
                else:
                    meme_path = music_output
            else:
                meme_path = music_output

            # (g3) Ses efektleri (varsa)
            sfx_events = clip.get("sfx_events", [])
            has_sfx = bool(sfx_events)
            sfx_path = EDITED_DIR / f"sfx_{clip_id}.mp4"
            if sfx_events:
                from services.auto_sfx import auto_sfx as _sfx2
                sfx_ok = await _sfx2.add_multiple_sfx(
                    str(meme_path), sfx_events, str(sfx_path),
                )
                if sfx_ok:
                    working_files.append(sfx_path)
                    has_sfx = True
                else:
                    sfx_path = meme_path
            else:
                sfx_path = meme_path

            # (h) Thumbnail uret (bir onceki asama'dan)
            thumb_path = EDITED_DIR / f"thumb_{clip_id}.jpg"
            await self._extract_thumbnail(str(sfx_path), str(thumb_path))

            # (i) Son export — platform profiline gore kodlama
            exported_path = EDITED_DIR / f"export_{clip_id}.mp4"
            await self._export_for_platform(
                str(sfx_path), str(exported_path), platform=platform,
            )
            working_files.append(exported_path)

            # Temizlik — intermediate dosyalari sil
            for f in working_files:
                if f.exists() and f not in (exported_path, raw_path):
                    f.unlink(missing_ok=True)

            result["status"] = "ready"
            result["output_path"] = str(exported_path)
            result["thumbnail_path"] = str(thumb_path) if thumb_path.exists() else None
            result["subtitle_path"] = str(sub_path) if has_subs else None
            result["completed_at"] = datetime.now(timezone.utc).isoformat()
            result["watermarked"] = True
            result["has_subtitles"] = has_subs
            result["has_music"] = has_music
            result["has_meme"] = has_meme
            result["has_sfx"] = has_sfx
            result["format"] = f"{VERT_WIDTH}x{VERT_HEIGHT}"
            result["fps"] = 30

            logger.info(
                "Klip duzenlendi [%s]: %s (score: %.1f) -> %dx%d @ 30fps | meme:%s sfx:%s music:%s",
                platform, title, score, VERT_WIDTH, VERT_HEIGHT,
                has_meme, has_sfx, has_music,
            )

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error("Klip edit hatasi [%s]: %s", clip_id, e)

        return result

    async def edit_batch(
        self,
        clips: list[dict[str, Any]],
        platform: str = "tiktok",
        max_concurrent: int = 2,
    ) -> list[dict[str, Any]]:
        """Birden fazla klibi paralel olarak duzenle."""
        self._is_processing = True
        results = []

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _edit_with_semaphore(clip):
            async with semaphore:
                return await self.edit_clip(clip, platform=platform)

        tasks = [_edit_with_semaphore(c) for c in clips]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        self._is_processing = False
        self._results = [r for r in results if isinstance(r, dict)]

        return self._results

    async def edit_multi_platform(
        self,
        clip: dict[str, Any],
        platforms: Optional[list[str]] = None,
    ) -> dict[str, dict[str, Any]]:
        """
        Bir klibi birden fazla platform icin ayri ayri export et.
        TikTok, Instagram Reels, YouTube Shorts gibi.
        """
        if platforms is None:
            platforms = ["tiktok", "instagram_reels", "youtube_shorts", "x"]

        outputs: dict[str, dict[str, Any]] = {}
        for plat in platforms:
            outputs[plat] = await self.edit_clip(clip, platform=plat)
        return outputs

    def get_results(self) -> list[dict[str, Any]]:
        """Son duzenlemelerin sonuclarini dondur."""
        return self._results

    def is_processing(self) -> bool:
        return self._is_processing

    # ── Internal Methods ──────────────────────────────────────────

    async def _auto_trim_inactive(
        self,
        input_path: str,
        output_path: str,
        noise_thresh: str = "-28dB",
        min_silence_dur: float = 0.5,
        freeze_noise: str = "0.001",
        min_freeze_dur: float = 0.6,
        min_segment_dur: float = 1.5,
        merge_gap: float = 0.3,
        max_duration: float = 60.0,
    ) -> float:
        """
        Rust (native) + FFmpeg (fallback) ile sessiz/donuk bolumleri kaldir.

        Priority:
          1. Rust trim-detector binary (native silence + freeze detection)
          2. FFmpeg silencedetect + freezedetect (Python parse)

        Returns:
            Kirlilmis videonun gercek suresi (saniye), 0.0 ise basarisiz.
        """
        import re as _re

        if not os.path.exists(input_path):
            return 0.0

        ffmpeg_bin = self._resolve_ffmpeg() or "ffmpeg"

        info_cmd = [ffmpeg_bin, "-i", input_path, "-f", "null", "-"]
        info_proc = await asyncio.create_subprocess_exec(
            *info_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, info_stderr = await info_proc.communicate()
        info_text = info_stderr.decode(errors="replace")

        dur_m = _re.search(r"Duration:\s+(\d+):(\d+):(\d+)\.(\d+)", info_text)
        if not dur_m:
            logger.warning("Auto-trim: cannot determine duration")
            return 0.0
        h, m, s, ms = int(dur_m.group(1)), int(dur_m.group(2)), int(dur_m.group(3)), int(dur_m.group(4))
        total_dur = h * 3600 + m * 60 + s + ms / 100

        if total_dur < 5:
            shutil.copy2(input_path, output_path)
            return total_dur

        # ── Strategy 1: Rust trim-detector (native) ──
        active_segments: list[tuple[float, float]] = []
        try:
            from shared.utils.trim_detector_client import detect_segments as _rust_detect

            rust_result = await _rust_detect(
                input_path,
                noise_threshold_db=float(_re.sub(r"[^\d.-]", "", noise_thresh)),
                min_silence_duration=min_silence_dur,
                freeze_noise=float(freeze_noise),
                min_freeze_duration=min_freeze_dur,
                min_segment_duration=min_segment_dur,
                merge_gap=merge_gap,
                max_duration=max_duration,
            )
            if rust_result and rust_result.get("active_segments"):
                raw = rust_result["active_segments"]
                active_segments = [(s[0], s[1]) for s in raw]
                logger.info("Auto-trim: Rust detector -> %d segments, kept %.1fs",
                            len(active_segments), rust_result.get("kept_duration", 0))
        except Exception as e:
            logger.debug("Rust trim-detector fallback: %s", e)

        # ── Strategy 2: FFmpeg fallback ──
        if not active_segments:
            boring_set: set[tuple[float, float]] = set()

            for label, filt in [
                ("silence", f"silencedetect=noise={noise_thresh}:d={min_silence_dur}"),
                ("freeze", f"freezedetect=noise={freeze_noise}:d={min_freeze_dur}"),
            ]:
                dc = [
                    ffmpeg_bin, "-y",
                    "-i", input_path,
                    "-af" if label == "silence" else "-vf", filt,
                    "-f", "null",
                    "-",
                ]
                dp = await asyncio.create_subprocess_exec(
                    *dc,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, dstderr = await dp.communicate()
                dout = dstderr.decode(errors="replace")

                starts = [float(x) for x in _re.findall(rf"{label}_start:\s+([\d.]+)", dout)]
                ends = [float(x) for x in _re.findall(rf"{label}_end:\s+([\d.]+)", dout)]
                for ss, se in zip(starts, ends):
                    boring_set.add((round(ss, 2), round(se, 2)))

            if not boring_set:
                shutil.copy2(input_path, output_path)
                return total_dur

            sorted_boring = sorted(boring_set, key=lambda x: x[0])
            merged_boring = [sorted_boring[0]] if sorted_boring else []
            for seg in sorted_boring[1:]:
                if seg[0] - merged_boring[-1][1] <= max(min_silence_dur, min_freeze_dur):
                    merged_boring[-1] = (merged_boring[-1][0], max(merged_boring[-1][1], seg[1]))
                else:
                    merged_boring.append(seg)

            prev_end = 0.0
            for bs, be in merged_boring:
                if bs - prev_end >= min_segment_dur:
                    active_segments.append((prev_end, bs))
                prev_end = max(prev_end, be)
            if total_dur - prev_end >= min_segment_dur:
                active_segments.append((prev_end, total_dur))

        if not active_segments:
            shutil.copy2(input_path, output_path)
            return total_dur

        # Merge nearby active segments
        active_segments.sort(key=lambda x: x[0])
        merged = [active_segments[0]]
        for seg in active_segments[1:]:
            if seg[0] - merged[-1][1] <= merge_gap:
                merged[-1] = (merged[-1][0], seg[1])
            else:
                merged.append(seg)

        # Cap total
        kept = 0.0
        capped = []
        for s, e in merged:
            dur = e - s
            if kept + dur > max_duration:
                dur = max_duration - kept
            if dur >= min_segment_dur:
                capped.append((s, s + dur))
                kept += dur
            if kept >= max_duration:
                break

        if len(capped) == 1:
            start, end = capped[0]
            cmd = [
                ffmpeg_bin, "-y",
                "-ss", f"{start:.3f}",
                "-i", input_path,
                "-t", f"{end - start:.3f}",
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                output_path,
            ]
            sp = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            await sp.communicate()
            logger.info("Auto-trim: 1 segment (%.1fs-%.1fs) kept %.1fs of %.1fs total", start, end, kept, total_dur)
            return end - start

        concat_file = output_path + ".concat.txt"
        try:
            total_kept = 0.0
            with open(concat_file, "w") as f:
                f.write("ffconcat version 1.0\n")
                for i, (start, end) in enumerate(capped):
                    dur = end - start
                    part = output_path.replace(".mp4", f"_p{i}.mp4")
                    pc = [
                        ffmpeg_bin, "-y",
                        "-ss", f"{start:.3f}",
                        "-i", input_path,
                        "-t", f"{dur:.3f}",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                        "-c:a", "aac", "-b:a", "96k",
                        part,
                    ]
                    pp = await asyncio.create_subprocess_exec(
                        *pc,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await pp.communicate()
                    if os.path.exists(part):
                        f.write(f"file {part}\n")
                        total_kept += dur

            cc = [
                ffmpeg_bin, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-c", "copy",
                output_path,
            ]
            spc = await asyncio.create_subprocess_exec(
                *cc,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            await spc.communicate()

            for i in range(len(capped)):
                Path(output_path.replace(".mp4", f"_p{i}.mp4")).unlink(missing_ok=True)
            Path(concat_file).unlink(missing_ok=True)

            removed = total_dur - total_kept
            logger.info("Auto-trim: removed %.1fs boring (%.0f%%) from %.1fs -> %.1fs (%d segments)",
                        removed, removed / total_dur * 100, total_dur, total_kept, len(capped))
            return total_kept
        except Exception as e:
            logger.warning("Auto-trim concat failed: %s", e)
            shutil.copy2(input_path, output_path)
            return total_dur

    async def _download_clip(self, url: str, output_path: str) -> bool:
        """Kick CDN'den clip video'sunu indir — multi-strategy. Dosya zaten varsa atla."""
        if not url:
            logger.warning("No URL provided for download")
            return False
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1024 * 1024:
            logger.info("Dosya zaten var, download atlandi: %s", output_path)
            return True

        # ── Strategy 1: FFmpeg with proper headers ──
        ffmpeg_bin = self._resolve_ffmpeg() or "ffmpeg"
        headers = (
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            " AppleWebKit/537.36 (KHTML, like Gecko)"
            " Chrome/125.0.0.0 Safari/537.36\r\n"
            "Referer: https://kick.com/\r\n"
        )
        try:
            cmd = [
                ffmpeg_bin, "-y",
                "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
                "-headers", headers,
                "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "-i", url,
                "-c", "copy",
                "-t", "120",
                "-movflags", "+faststart",
                output_path,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1024 * 1024:
                return True
            logger.warning("Strategy 1 (ffmpeg) failed: %s", stderr.decode()[:200])
            Path(output_path).unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Strategy 1 (ffmpeg) error: %s", e)

        # ── Strategy 2: yt-dlp fallback ──
        try:
            import yt_dlp
            ydl_opts = {
                "outtmpl": output_path,
                "format": "best[ext=mp4]/best",
                "quiet": True,
                "noprogress": True,
                "http_headers": {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://kick.com/",
                },
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024 * 1024:
                return True
            Path(output_path).unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Strategy 2 (yt-dlp) failed: %s", e)

        # ── Strategy 3: curl_cffi HLS download (Cloudflare bypass, segment bazinda) ──
        if ".m3u8" in url:
            ok = await self._download_hls_via_curl_cffi(url, output_path)
            if ok:
                return True

        return False

    async def _download_hls_via_curl_cffi(self, url: str, output_path: str) -> bool:
        """curl_cffi ile HLS playlist + segmentleri indir, FFmpeg ile birlestir.
        m3u8'i curl_cffi ile indir (TLS fingerprint + cookie bypass), unique .ts
        dosyalarini indir, ardindan FFmpeg HLS demuxer'a lokal dosyalari gostererek
        BYTERANGE dahil her seyi native cozmesini sagla."""
        logger.info("HLS download via curl_cffi: %s", url)
        seg_dir = Path(tempfile.mkdtemp(prefix="hls_seg_"))
        try:
            from curl_cffi.requests import Session as CurlSession

            session = CurlSession(impersonate="chrome124")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Referer": "https://kick.com/",
            }

            # 1. m3u8 playlist'i indir
            resp = await asyncio.to_thread(session.get, url, headers=headers, timeout=30)
            resp.raise_for_status()
            playlist_text = resp.text

            if not playlist_text.startswith("#EXTM3U"):
                logger.warning("Not a valid m3u8 playlist")
                return False

            # 2. Unique segment dosyalarini bul
            base_url = url[: url.rfind("/") + 1]

            # Variant playlist (multi-bitrate) — ilk alt playlist'i takip et
            if "#EXT-X-STREAM-INF" in playlist_text:
                for line in playlist_text.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    sub_url = line if line.startswith("http") else base_url + line
                    logger.info("Following variant playlist: %s", sub_url)
                    resp = await asyncio.to_thread(session.get, sub_url, headers=headers, timeout=30)
                    resp.raise_for_status()
                    playlist_text = resp.text
                    if not playlist_text.startswith("#EXTM3U"):
                        logger.warning("Sub-playlist not valid m3u8")
                        return False
                    break
                    
            unique_files: dict[str, str] = {}
            for line in playlist_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("http://") or line.startswith("https://"):
                    seg_file_url = line
                else:
                    seg_file_url = base_url + line
                # BYTERANGE ile ayni dosyaya birden cok referans olabilir
                fname = Path(seg_file_url.split("?")[0]).name
                unique_files[fname] = seg_file_url

            if not unique_files:
                logger.warning("No segment files found in m3u8")
                return False

            # 3. Unique segment dosyalarini indir
            ffmpeg_bin = self._resolve_ffmpeg() or "ffmpeg"
            for fname, seg_url in unique_files.items():
                local_path = seg_dir / fname
                try:
                    seg_resp = await asyncio.to_thread(session.get, seg_url, headers=headers, timeout=60)
                    seg_resp.raise_for_status()
                    with open(local_path, "wb") as f:
                        f.write(seg_resp.content)
                    logger.debug("Downloaded %s (%.1f MB)", fname, len(seg_resp.content) / 1024 / 1024)
                except Exception as e:
                    logger.warning("Segment download failed %s: %s", fname, e)

            # 4. m3u8'i lokal path'lerle degistir ve kaydet
            local_playlist = seg_dir / "playlist.m3u8"
            def _fix_path(m: re.Match) -> str:
                seg_line = m.group(0)
                fname = Path(seg_line.split("?")[0]).name
                local_ts = seg_dir / fname
                if local_ts.exists():
                    return str(local_ts).replace("\\", "/")
                return seg_line

            # Segment URL'lerini lokal path'lerle degistir (EXTINF satirindan sonraki URL)
            fixed_playlist = re.sub(
                r"^[^#].+$",
                _fix_path,
                playlist_text,
                flags=re.MULTILINE,
            )
            local_playlist.write_text(fixed_playlist, encoding="utf-8")

            # 5. FFmpeg HLS demuxer ile lokal playlist'ten birlestir
            cmd = [
                ffmpeg_bin, "-y",
                "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                "-i", str(local_playlist),
                "-c", "copy",
                "-movflags", "+faststart",
                output_path,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1024 * 1024:
                logger.info("HLS via curl_cffi: OK (%.1f MB, %d unique files)",
                            os.path.getsize(output_path) / 1024 / 1024, len(unique_files))
                return True

            # 5b. Fallback: concat demuxer (BYTERANGE yoksa calisir)
            logger.warning("HLS demuxer failed (code %d), trying concat fallback", proc.returncode)
            downloaded = sorted(seg_dir.glob("*.ts")) + sorted(seg_dir.glob("*.m4s")) + sorted(seg_dir.glob("*.mp4"))
            if downloaded:
                concat_file = seg_dir / "concat.txt"
                with open(concat_file, "w") as f:
                    for seg_path in downloaded:
                        safe = str(seg_path).replace("\\", "/")
                        f.write(f"file '{safe}'\n")
                cmd2 = [
                    ffmpeg_bin, "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(concat_file),
                    "-c", "copy",
                    "-movflags", "+faststart",
                    output_path,
                ]
                proc2 = await asyncio.create_subprocess_exec(
                    *cmd2,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr2 = await proc2.communicate()
                if proc2.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1024 * 1024:
                    logger.info("HLS via curl_cffi (concat): OK (%.1f MB, %d files)",
                                os.path.getsize(output_path) / 1024 / 1024, len(downloaded))
                    return True
                logger.warning("Concat fallback failed (code %d): %s", proc2.returncode, stderr2.decode()[:300])

            return False

        except ImportError:
            logger.warning("curl_cffi not available for HLS download")
            return False
        except Exception as e:
            logger.warning("HLS via curl_cffi failed: %s", e)
            return False
        finally:
            shutil.rmtree(seg_dir, ignore_errors=True)

    @staticmethod
    def _resolve_ffmpeg() -> Optional[str]:
        """Find ffmpeg binary, including WinGet install locations."""
        found = shutil.which("ffmpeg")
        if found:
            return found
        if os.name == "nt":
            local = os.environ.get("LOCALAPPDATA", "")
            if local:
                roots = [
                    Path(local) / "Microsoft" / "WinGet" / "Packages",
                    Path(local) / "Programs",
                ]
                for root in roots:
                    if not root.exists():
                        continue
                    for match in root.rglob("ffmpeg.exe"):
                        if match.parent.name == "bin":
                            return str(match)
        return None

    async def _crop_to_vertical(self, input_path: str, output_path: str, duration: float = 15.0):
        """
        16:9 yatay videoyu 9:16 dikey formata kirp.
        Adobe Premiere seviyesinde 'Ken Burns' zoompan efekti uygular.
        """
        from services.smart_crop import generate_zoompan_filter

        source_w, source_h = 1920, 1080
        try:
            from shared.utils.ffmpeg_runner import ffmpeg_runner

            probe = await ffmpeg_runner.probe(input_path)
            video_stream = next(
                (s for s in (probe or {}).get("streams", []) if s.get("codec_type") == "video"),
                None,
            )
            if video_stream:
                source_w = int(video_stream.get("width") or source_w)
                source_h = int(video_stream.get("height") or source_h)
                duration = float((probe or {}).get("format", {}).get("duration") or duration)
        except Exception as exc:
            logger.debug("Crop probe fallback: %s", exc)

        focus_point = (0.5, 0.5)
        try:
            from services.face_tracker import face_tracker

            face_result = await face_tracker.get_face_trajectory(input_path, fps=1)
            trajectory = face_result.get("trajectory", [])
            if trajectory:
                # Median is resistant to scene cuts and short false detections.
                xs = sorted(float(point["x"]) for point in trajectory)
                ys = sorted(float(point["y"]) for point in trajectory)
                middle = len(trajectory) // 2
                focus_point = (xs[middle], ys[middle])
        except Exception as exc:
            logger.debug("Face-aware crop fallback: %s", exc)

        zoompan_filter = generate_zoompan_filter(
            source_w=source_w, source_h=source_h,
            target_w=VERT_WIDTH, target_h=VERT_HEIGHT,
            duration_s=duration,
            fps=30,
            zoom_start=1.0,
            zoom_end=1.07,
            focus_point=focus_point,
        )

        ffmpeg_bin = self._resolve_ffmpeg() or "ffmpeg"
        cmd = [
            ffmpeg_bin, "-y",
            "-i", input_path,
            "-vf", zoompan_filter,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            error = stderr.decode(errors="replace")[-1000:]
            Path(output_path).unlink(missing_ok=True)
            raise RuntimeError(f"Vertical crop failed: {error}")

    async def _trim_clip(
        self,
        input_path: str,
        output_path: str,
        start: float = 0.0,
        duration: float = 30.0,
    ):
        """Klibi belirli baslangic ve sureye gore kirp."""
        duration = min(max(duration, 5), 120)
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}",
            "-i", input_path,
            "-t", f"{duration:.3f}",
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    async def _add_hook_text(
        self,
        input_path: str,
        output_path: str,
        hook_text: str,
        duration: float = 3.0,
    ):
        """
        Video'nun ilk N saniyesine buyuk, dikkat cekici hook text overlay ekle.
        TikTok/Insta tarzi: buyuk font, merkez, yuksek kontrast, fade-in animasyon.

        Fade-in: 0.3sn icinde gorunur olur, 3.sn'de kaybolur.
        Konum: Dikey videonun ust-orta bolgesi (safe zone icinde).
        """
        if not hook_text or not hook_text.strip():
            # Hook text yoksa sadece codec copy ile kopyala
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-c", "copy", output_path,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return

        # Hook text'i temizle — FFmpeg drawtext icin ozel karakterleri kacir
        clean_text = hook_text.replace("'", "'\\''").replace(":", "\\:")
        clean_text = clean_text.replace('"', '\\"')
        # Maksimum 60 karakter
        if len(clean_text) > 60:
            clean_text = clean_text[:57] + "..."

        # Fade-in alpha: 0->1 ilk 0.3sn, 1 sabit, son 0.5sn'de fade-out
        fade_in_end = 0.3
        fade_out_start = duration - 0.5
        # drawtext alpha ifadesi
        alpha_expr = (
            f"if(lt(t\\,{fade_in_end})\\,"
            f"t/{fade_in_end}\\,"
            f"if(lt(t\\,{fade_out_start})\\,"
            f"1\\,"
            f"(1-(t-{fade_out_start})/0.5)))"
        )

        # Dikey videoda yukari-orta bolge — safe zone icinde
        # y = height * 0.22 (safe zone ust siniri biraz alti)
        drawtext_filter = (
            f"drawtext=text='{clean_text}':"
            f"fontsize=56:"
            f"fontcolor=white:"
            f"borderw=4:"
            f"bordercolor=black:"
            f"alpha='{alpha_expr}':"
            f"x=(w-tw)/2:"
            f"y=h*0.22"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", drawtext_filter,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "copy",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("Hook text failed, copying as-is: %s", stderr.decode()[:200])
            # Fallback: hook text olmadan kopyala
            fallback = ["ffmpeg", "-y", "-i", input_path, "-c", "copy", output_path]
            proc2 = await asyncio.create_subprocess_exec(
                *fallback,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc2.communicate()

    async def _generate_karaoke_subtitles(
        self,
        video_path: str,
        output_ass: str,
        platform: str = "tiktok",
    ) -> bool:
        """
        Whisper ile kelime kelime zamanlama cikar, karaoke ASS dosyasi uret.
        word_highlight servisini kullanir veya fallback olarak SRT uretir.
        """
        # word_highlight servisini dene
        try:
            from services.word_highlight import word_highlight

            words = await word_highlight.extract_timings_from_video(video_path)
            if not words:
                logger.debug("No word timings from word_highlight, falling back to SRT")
                return await self._generate_subtitles_fallback(video_path, output_ass)

            # Platform icin uygun renk paleti sec
            palette_map = {
                "tiktok": "neon",
                "instagram_reels": "neon",
                "youtube_shorts": "ice",
            }
            palette = palette_map.get(platform, "neon")

            # ASS uret
            ass_content = word_highlight.generate_karaoke_ass(
                words,
                video_width=VERT_WIDTH,
                video_height=VERT_HEIGHT,
                palette=palette,
                font_size=48,
                max_chars_per_line=28,
                position="bottom",
                outline=3.0,
                shadow=2.0,
            )

            # Dosyaya yaz
            Path(output_ass).write_text(ass_content, encoding="utf-8")
            logger.info("Karaoke ASS uretildi: %s (%d kelime)", output_ass, len(words))
            return True

        except ImportError:
            logger.debug("word_highlight servisi mevcut degil, SRT fallback")
        except Exception as e:
            logger.debug("Karaoke subtitle generation failed: %s", e)

        # Fallback: SRT uret ve .ass uzantisina kaydet (FFmpeg subtitles filter kullanir)
        return await self._generate_subtitles_fallback(video_path, output_ass)

    async def _generate_subtitles_fallback(
        self,
        video_path: str,
        output_srt: str,
    ) -> bool:
        """Whisper ile SRT altyazi uret (fallback)."""
        try:
            from services.llm_engine import llm_engine

            result = await llm_engine.transcribe(video_path)
            if not result or not result.get("segments"):
                return False

            # SRT formatinda yaz, ama .ass uzantisiyla (FFmpeg subtitles filter her ikisini de alir)
            srt_text = ""
            for i, seg in enumerate(result["segments"], 1):
                start = seg.get("start", 0)
                end = seg.get("end", 0)
                text = seg.get("text", "").strip()
                if text:
                    srt_text += f"{i}\n"
                    srt_text += f"{self._srt_time(start)} --> {self._srt_time(end)}\n"
                    srt_text += f"{text}\n\n"

            Path(output_srt).write_text(srt_text, encoding="utf-8")
            return os.path.exists(output_srt)
        except Exception as e:
            logger.debug("Subtitle generation skipped: %s", e)
            return False

    async def _burn_subtitles(
        self,
        video_path: str,
        ass_path: str,
        output_path: str,
        platform: str = "tiktok",
    ):
        """
        Altyaziyi video'ya yak — TikTok/Insta optimized style.
        Bold sans-serif, beyaz + siyah outline, center-lower third safe zone.
        """
        safe = SAFE_ZONES.get(platform, SAFE_ZONES["tiktok"])

        # Safe zone'a gore MarginV hesapla
        # Altyazi center-lower third'te gorunmeli
        # MarginV = videonun altindan uzaklik (piksel)
        # Center-bottom: %65 -> alt sinir %65, altyazi %55 civarinda olmali
        margin_v = int(VERT_HEIGHT * (1.0 - (safe["center_top_pct"] + safe["center_bottom_pct"]) / 2 + 0.15))

        # .ass dosyasi mi SRT mi kontrol et
        is_ass = ass_path.lower().endswith(".ass")

        if is_ass:
            # ASS dosyasi — dogrudan kullan
            ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:")
            vf = f"ass='{ass_escaped}'"
        else:
            # SRT dosyasi — force_style ile TikTok optimized
            style = (
                f"FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,"
                f"OutlineColour=&H00000000,BackColour=&H80000000,"
                f"Outline=2,Shadow=1,Bold=1,"
                f"Alignment=2,MarginV={margin_v}"
            )
            srt_escaped = ass_path.replace("\\", "/").replace(":", "\\:")
            vf = f"subtitles='{srt_escaped}':force_style='{style}'"

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "copy",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("Subtitle burn failed: %s", stderr.decode()[:300])
            # Fallback: altyazi olmadan kopyala
            cmd_fb = ["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path]
            proc2 = await asyncio.create_subprocess_exec(
                *cmd_fb,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc2.communicate()

    async def _add_watermark(
        self,
        input_path: str,
        output_path: str,
        platform: str = "tiktok",
    ):
        """
        TikTok/Insta optimized watermark ekle.
        - Kucuk, ince, saydam
        - Guvenli bolge: sag alt, ama platform UI'un ustunde
        - Sade, dikkat dagiticak sekilde degil
        """
        safe = SAFE_ZONES.get(platform, SAFE_ZONES["tiktok"])

        # Watermark: sag alt ama UI zone'un ustunde
        # x: 20px sagdan, y: UI zone sinirinin biraz ustunden
        # y = height * (1 - bottom_pct) - 30
        wm_y = int(VERT_HEIGHT * (1.0 - safe["bottom_pct"]) - 30)

        text = self.watermark_text.replace("'", "'\\''").replace(":", "\\:")

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", (
                f"drawtext=text='{text}':"
                f"fontsize=18:"
                f"fontcolor=white@0.5:"
                f"borderw=1:"
                f"bordercolor=black@0.3:"
                f"x=w-tw-20:"
                f"y={wm_y}"
            ),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "copy",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("Watermark failed, copying as-is: %s", stderr.decode()[:200])
            cmd_fb = ["ffmpeg", "-y", "-i", input_path, "-c", "copy", output_path]
            proc2 = await asyncio.create_subprocess_exec(
                *cmd_fb,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc2.communicate()

    async def _export_for_platform(
        self,
        input_path: str,
        output_path: str,
        platform: str = "tiktok",
    ):
        """
        Platform-specific final export.
        H.264, AAC stereo, 30fps, platform bitrates + movflags.
        """
        # Platform export ayarlari (2026 research e gore)
        # TikTok: 10-15 Mbps, H.264 High@4, 30fps, AAC 192k stereo, <287MB
        # Reels: 12-15 Mbps, H.264 High@4.2, 30fps, AAC 192k stereo, <4GB
        # Shorts: 10-15 Mbps, H.264 High@4, 30fps, AAC 192k stereo, <256GB
        # X/Twitter: 5-8 Mbps, H.264 High@3.1, 30fps, AAC 128k, <512MB, 1280x720
        export_config = {
            "tiktok": {
                "video_bitrate": "10M",
                "maxrate": "12M",
                "bufsize": "20M",
                "audio_bitrate": "192k",
                "crf": 20,
                "preset": "medium",
                "profile": "high",
                "level": "4.0",
                "extra_args": ["-movflags", "+faststart", "-tag:v", "avc1"],
            },
            "instagram_reels": {
                "video_bitrate": "12M",
                "maxrate": "15M",
                "bufsize": "24M",
                "audio_bitrate": "192k",
                "crf": 18,
                "preset": "medium",
                "profile": "high",
                "level": "4.2",
                "extra_args": ["-movflags", "+faststart", "-tag:v", "avc1"],
            },
            "youtube_shorts": {
                "video_bitrate": "10M",
                "maxrate": "14M",
                "bufsize": "22M",
                "audio_bitrate": "192k",
                "crf": 19,
                "preset": "medium",
                "profile": "high",
                "level": "4.0",
                "extra_args": ["-movflags", "+faststart", "-tag:v", "avc1"],
            },
            "x": {
                "video_bitrate": "5M",
                "maxrate": "8M",
                "bufsize": "14M",
                "audio_bitrate": "128k",
                "crf": 23,
                "preset": "fast",
                "profile": "high",
                "level": "3.1",
                "extra_args": ["-movflags", "+faststart", "-tag:v", "avc1"],
            },
        }

        cfg = export_config.get(platform, export_config["tiktok"])

        # X/Twitter için yatay 1280x720, diğerleri için 9:16 1080x1920
        if platform == "x":
            scale_filter = "scale=1280:720:flags=lanczos"
            pix_fmt = "yuv420p"
        else:
            scale_filter = f"scale={VERT_WIDTH}:{VERT_HEIGHT}:flags=lanczos"
            pix_fmt = "yuv420p"

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", scale_filter,
            "-c:v", "libx264",
            "-profile:v", cfg.get("profile", "high"),
            "-level", cfg.get("level", "4.0"),
            "-b:v", cfg["video_bitrate"],
            "-maxrate", cfg.get("maxrate", cfg["video_bitrate"]),
            "-bufsize", cfg.get("bufsize", "16M"),
            "-c:a", "aac",
            "-b:a", cfg["audio_bitrate"],
            "-ac", "2",
            "-ar", "44100",
            "-r", "30",
            "-crf", str(cfg["crf"]),
            "-preset", cfg["preset"],
            "-movflags", "+faststart",
            "-pix_fmt", pix_fmt,
            output_path,
        ]

        # Ekstra platform argumanlari
        for arg in cfg.get("extra_args", []):
            if arg not in cmd:
                cmd.insert(-1, arg)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("Export failed [%s]: %s", platform, stderr.decode()[:300])
            # Fallback: copy
            cmd_fb = ["ffmpeg", "-y", "-i", input_path, "-c", "copy", output_path]
            proc2 = await asyncio.create_subprocess_exec(
                *cmd_fb,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc2.communicate()

    async def _generate_subtitles(self, audio_path: str, output_srt: str) -> bool:
        """Whisper ile altyazi uret (eski API uyumlulugu icin korundu)."""
        return await self._generate_subtitles_fallback(audio_path, output_srt)

    async def edit_clip_with_viral_recommendations(
        self,
        clip: dict[str, Any],
        viral_recommendations: dict[str, Any],
        platform: str = "tiktok",
    ) -> dict[str, Any]:
        """
        Viral önerilerini kullanarak klibi düzenle.
        
        Args:
            clip: Clip bilgileri
            viral_recommendations: Edit recommendation engine'den gelen kapsamlı öneriler
            platform: Hedef platform
        
        Returns:
            Edit sonucu
        """
        try:
            # Viral önerilerinden edit spec'i al
            edit_spec = viral_recommendations.get("edit_specification", {})
            scored_recommendations = viral_recommendations.get("scored_recommendations", [])
            
            # Clip verilerini viral önerilerle güncelle
            clip.update({
                "meme_overlays": edit_spec.get("meme_overlays", []),
                "sfx_events": edit_spec.get("sfx_events", []),
                "music_path": edit_spec.get("audio_strategy", {}).get("music_path", ""),
                "music_volume_db": edit_spec.get("audio_strategy", {}).get("volume", -18.0),
                "caption_style": edit_spec.get("caption_strategy", {}).get("style", "karaoke"),
                "hook_suggestion": edit_spec.get("hook_strategy", {}).get("description", clip.get("title", "")),
            })
            
            # Standard edit pipeline'ını viral efektlerle çalıştır
            result = await self.edit_clip(
                clip=clip,
                platform=platform,
                enable_viral_effects=True,
            )
            
            # Recommendation bilgilerini sonuç ekle
            result["viral_recommendations_applied"] = True
            result["confidence_score"] = viral_recommendations.get("confidence_score", 0.0)
            result["applied_recommendations_count"] = len(scored_recommendations)
            result["top_recommendations"] = [
                {
                    "type": rec["type"],
                    "score": rec["overall_score"],
                    "priority": rec["priority"]
                }
                for rec in scored_recommendations[:5]
            ]
            
            logger.info("Viral önerilerle klip düzenlendi: confidence=%.1f%%", 
                       result["confidence_score"] * 100)
            
            return result
            
        except Exception as e:
            logger.error("Viral önerili edit hatası: %s", e)
            # Fallback: standard edit
            return await self.edit_clip(clip, platform, enable_viral_effects=False)

    async def _extract_thumbnail(self, video_path: str, thumb_path: str):
        """Videonun ilk karesinden thumbnail cikar."""
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", "select=eq(n\\,0)",
            "-vframes", "1",
            "-q:v", "2",
            thumb_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    @staticmethod
    def _srt_time(seconds: float) -> str:
        """Saniye -> SRT zaman formati (HH:MM:SS,mmm)."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# Singleton
auto_editor = AutoEditor()
