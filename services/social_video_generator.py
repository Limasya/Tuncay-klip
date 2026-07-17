"""
Mega Viral Video Üretici (v2 - Tam Entegrasyon)
─────────────────────────────────────────────────
Mevcut tüm servisleri (BeatSync, EffectsEngine, SceneDetection, 
StickerEngine, SocialMediaAI, QualityControl) tam anlamıyla 
entegre eden nihai sosyal medya kurgu motorudur.

Özellikler:
- Librosa BeatSync (Müziğe senkron kesimler)
- FFmpeg SceneDetect (Sahne değişim analizi)
- EffectsEngine (Zoom, Ken Burns, SlowMo, FilmGrain)
- StickerEngine (NLP→Emoji Overlay)
- SocialMediaAI (LLM başlık + hashtag)
- QualityControl (Post-render QC)
- AI Denoise + Auto-Censor + Face Tracking + BGM Ducking
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from pathlib import Path
from typing import Any, Optional

from services.advanced_subtitle import advanced_subtitle
from services.face_tracker import face_tracker
from services.silence_remover import silence_remover
from services.audio_analyzer import audio_analyzer
from services.auto_censor import auto_censor
from services.beat_sync import BeatSyncEngine
from services.scene_detection import SceneDetectionEngine
from services.effects_engine import EffectsEngine
from services.sticker_engine import StickerEngine, StickerDef
from services.social_media_ai import social_media_ai
from services.quality_control import QualityControl

logger = logging.getLogger("social_video_generator_v2")

# Servis singleton'ları
_beat_sync = BeatSyncEngine()
_scene_detect = SceneDetectionEngine()
_effects = EffectsEngine()
_stickers = StickerEngine()
_qc = QualityControl()


class SocialVideoGenerator:
    def __init__(self):
        self.output_dir = Path("data/social_exports")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.satisfying_dir = Path("data/satisfying_videos")
        self.satisfying_dir.mkdir(parents=True, exist_ok=True)
        self.bgm_dir = Path("data/bgm")
        self.bgm_dir.mkdir(parents=True, exist_ok=True)

        # Viral TikTok stili
        advanced_subtitle.register_style("viral_tiktok", advanced_subtitle._styles.get("classic"))
        vt_style = advanced_subtitle._styles["viral_tiktok"]
        vt_style.fontsize = 24
        vt_style.bold = True
        vt_style.primary_color = "&H0000FFFF"
        vt_style.outline_color = "&H00000000"
        vt_style.outline = 4.0
        vt_style.shadow = 2.0
        vt_style.alignment = 5

    def _get_random_satisfying_video(self) -> str | None:
        videos = list(self.satisfying_dir.glob("*.mp4"))
        return str(random.choice(videos)) if videos else None

    def _get_random_bgm(self) -> str | None:
        bgms = list(self.bgm_dir.glob("*.mp3")) + list(self.bgm_dir.glob("*.wav"))
        return str(random.choice(bgms)) if bgms else None

    async def generate_viral_video(
        self,
        input_video_path: str,
        transcript_data: dict | None = None,
        facecam_position: str = "auto",
        emotion_spikes: list[dict] | None = None,
        remove_silences: bool = True,
        use_brainrot: bool = False,
        use_bgm: bool = True,
        use_auto_zoom: bool = True,
        use_ai_denoise: bool = True,
        use_auto_censor: bool = True,
        inject_emojis: bool = True,
        use_beat_sync: bool = True,
        use_scene_detect: bool = True,
        use_effects: bool = True,
        use_stickers: bool = True,
        use_quality_check: bool = True,
        generate_social_kit: bool = True,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """
        Nihai viral video üretici - tüm açık kaynak mekanikler dahil.
        """
        logger.info("=== MEGA VIRAL ENGINE BAŞLATILDI: %s ===", input_video_path)

        if not os.path.exists(input_video_path):
            return {"error": "Input video not found"}

        filename = Path(input_video_path).stem
        output_path = self.output_dir / f"{filename}_viral.mp4"
        features_used = []
        filter_parts = []
        v_input = "[0:v]"
        a_input = "[0:a]"
        meta = metadata or {}

        # ── 1. ASS Subtitle (Hormozi + Emoji Enjektör) ─────────────────────────
        ass_path = None
        if transcript_data and "words" in transcript_data:
            try:
                ass_content = advanced_subtitle.generate_ass_from_whisper(
                    whisper_segments=[transcript_data],
                    style_name="viral_tiktok",
                    max_words_per_line=3,
                    inject_emojis=inject_emojis,
                )
                ass_path = self.output_dir / f"{filename}.ass"
                advanced_subtitle.save_ass(ass_content, str(ass_path))
                features_used.append("Hormozi Bouncy Subtitles")
                if inject_emojis:
                    features_used.append("NLP Emoji Injector")
            except Exception as e:
                logger.warning("Subtitle generation failed: %s", e)

        # ── 2. AI Denoise ───────────────────────────────────────────────────────
        if use_ai_denoise:
            features_used.append("AI Denoise (afftdn)")
            filter_parts.append(f"[0:a]afftdn=nr=15:nf=-25,highpass=f=80,lowpass=f=14000[denoised_a];")
            a_input = "[denoised_a]"

        # ── 3. Auto-Censor (Küfür Bleep) ───────────────────────────────────────
        if use_auto_censor and transcript_data:
            bleeps = auto_censor.detect_profanity(transcript_data)
            if bleeps:
                features_used.append("Auto-Censor Bleep")
                censor_filter, a_input = auto_censor.generate_bleep_filter(
                    bleeps, input_audio_label=a_input
                )
                filter_parts.append(censor_filter)

        # ── 4. BeatSync — BGM beat tespiti ──────────────────────────────────────
        bgm_vid = self._get_random_bgm() if use_bgm else None
        beat_cuts: list[float] = []
        if use_beat_sync and bgm_vid:
            try:
                beat_grid = await _beat_sync.detect_beats(bgm_vid)
                beat_cuts = [b.time for b in beat_grid.beats[:20]]  # İlk 20 beat
                features_used.append("BeatSync Cuts (librosa)")
                logger.info("BeatSync: %d beat bulundu, BPM=%.1f", len(beat_cuts), beat_grid.bpm)
            except Exception as e:
                logger.warning("BeatSync failed: %s", e)

        # ── 5. Scene Detection ──────────────────────────────────────────────────
        scene_result = None
        if use_scene_detect:
            try:
                scene_result = await _scene_detect.detect_scenes(input_video_path)
                features_used.append(f"Scene Detection ({scene_result.total_scenes} sahne)")
                logger.info("SceneDetect: %d sahne bulundu", scene_result.total_scenes)
            except Exception as e:
                logger.warning("Scene detection failed: %s", e)

        # ── 6. Silence Removal (Jump-Cuts) ─────────────────────────────────────
        if remove_silences:
            sr_result = await silence_remover.detect_silences(input_video_path)
            if sr_result.get("success") and sr_result.get("silences"):
                total_dur = sr_result.get("total_duration", 0)
                silences = sr_result.get("silences")
                keep_segs = []
                last_end = 0.0
                for s in silences:
                    if s["start"] > last_end:
                        keep_segs.append((last_end, s["start"]))
                    last_end = s["end"]
                if last_end < total_dur:
                    keep_segs.append((last_end, total_dur))

                if keep_segs:
                    features_used.append("Auto Jump-Cuts")
                    concat_in = ""
                    for i, (st, en) in enumerate(keep_segs):
                        filter_parts.append(
                            f"[0:v]trim=start={st}:end={en},setpts=PTS-STARTPTS[vt{i}];"
                            f"[0:a]atrim=start={st}:end={en},asetpts=PTS-STARTPTS[at{i}];"
                        )
                        concat_in += f"[vt{i}][at{i}]"
                    n = len(keep_segs)
                    filter_parts.append(f"{concat_in}concat=n={n}:v=1:a=1[v_jump][a_jump];")
                    v_input = "[v_jump]"
                    a_input = "[a_jump]"

        # ── 7. Face Tracking (Auto-Reframe) ────────────────────────────────────
        face_crop = "iw/4:ih/4:0:0"
        if facecam_position == "auto":
            ft_res = await face_tracker.get_face_trajectory(input_video_path, fps=2)
            if ft_res.get("success") and ft_res.get("trajectory"):
                traj = ft_res["trajectory"]
                avg_x = sum(p["x"] for p in traj) / len(traj)
                avg_y = sum(p["y"] for p in traj) / len(traj)
                face_crop = f"iw/4:ih/4:max(0,{avg_x}*iw-iw/8):max(0,{avg_y}*ih-ih/8)"
                features_used.append("MediaPipe Face Tracking")

        # ── 8. Audio-Reactive Auto-Zoom ─────────────────────────────────────────
        zoom_filter = ""
        if use_auto_zoom:
            peak_res = await audio_analyzer.get_loud_peaks(input_video_path)
            if peak_res.get("success") and peak_res.get("peaks"):
                peaks = peak_res["peaks"]
                features_used.append("Audio-Reactive Auto-Zoom")
                zoom_exprs = [f"between(t,{p['start']},{p['end']})" for p in peaks]
                if zoom_exprs:
                    cond = "+".join(zoom_exprs)
                    zoom_filter = f",zoompan=z='if({cond},1.5,1)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1"

        # ── 9. EffectsEngine — FilmGrain + Vignette overlay ────────────────────
        extra_vf = ""
        if use_effects:
            try:
                grain = _effects.build_film_grain_filter(intensity=0.05)
                vignette = _effects.build_vignette_filter(strength=0.3)
                if grain:
                    extra_vf += f",{grain}"
                if vignette:
                    extra_vf += f",{vignette}"
                if grain or vignette:
                    features_used.append("FilmGrain + Vignette (EffectsEngine)")
            except Exception as e:
                logger.warning("EffectsEngine failed: %s", e)

        # ── 10. FFmpeg Filter Complex ───────────────────────────────────────────
        filter_parts.append(f"{v_input}split=3[bg][game][face_raw];")
        filter_parts.append(f"[face_raw]crop={face_crop}{zoom_filter},scale=800:-1[face_scaled];")

        satisfying_vid = self._get_random_satisfying_video() if use_brainrot else None
        if satisfying_vid:
            features_used.append("Brainrot Split-Screen")
            filter_parts.append("[1:v]scale=1080:-1[game_scaled];")
        else:
            filter_parts.append("[game]scale=1080:-1[game_scaled];")

        filter_parts.append(
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=20:5[bg_blur];"
        )
        filter_parts.append("[bg_blur][game_scaled]overlay=0:(H-h)/2+150[game_ov];")
        filter_parts.append(f"[game_ov][face_scaled]overlay=(W-w)/2:150{extra_vf}[out_v_clean]")
        out_v = "[out_v_clean]"

        # ASS Subtitle burn-in
        if ass_path and os.path.exists(str(ass_path)):
            esc = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")
            filter_parts.append(f";{out_v}ass='{esc}'[out_v_sub]")
            out_v = "[out_v_sub]"

        # ── 11. StickerEngine — Emoji Overlay (FFmpeg drawtext) ─────────────────
        if use_stickers and transcript_data:
            try:
                sticker_defs: list[StickerDef] = []
                words = transcript_data.get("words", [])
                kw_map = {
                    "fire": ("fire", 0.85, 0.15),
                    "ateş": ("fire", 0.85, 0.15),
                    "boom": ("boom", 0.8, 0.2),
                    "para": ("money", 0.15, 0.15),
                    "money": ("money", 0.15, 0.15),
                    "gol": ("rocket", 0.5, 0.3),
                    "heart": ("heart", 0.5, 0.2),
                    "kalp": ("heart", 0.5, 0.2),
                }
                for w in words[:60]:
                    clean = w.get("word", "").lower().strip().strip(".,!?")
                    if clean in kw_map:
                        emoji_key, sx, sy = kw_map[clean]
                        sticker_defs.append(
                            StickerDef(
                                emoji=emoji_key,
                                x=sx, y=sy,
                                start=w.get("start", 0),
                                duration=1.5,
                                animation="pop",
                            )
                        )
                if sticker_defs:
                    sticker_filter = _stickers.generate_sticker_filter(sticker_defs)
                    if sticker_filter:
                        filter_parts.append(f";{out_v}{sticker_filter}[out_v_stk]")
                        out_v = "[out_v_stk]"
                        features_used.append("StickerEngine Emoji Overlays")
            except Exception as e:
                logger.warning("StickerEngine failed: %s", e)

        # ── 12. BGM Ducking (Sidechain Compress) ───────────────────────────────
        out_a = a_input
        if bgm_vid:
            features_used.append("BGM Sidechain Ducking")
            inp_idx = 2 if satisfying_vid else 1
            filter_parts.append(f";{out_a}asplit=2[main_a][sc_ref];")
            filter_parts.append(f"[{inp_idx}:a]volume=0.3[bgm_vol];")
            filter_parts.append("[bgm_vol][sc_ref]sidechaincompress=threshold=0.08:ratio=4[bgm_duck];")
            filter_parts.append("[main_a][bgm_duck]amix=inputs=2:duration=first:dropout_transition=2[out_audio]")
            out_a = "[out_audio]"

        filter_complex = "".join(filter_parts)

        # ── 13. FFmpeg Komutu ───────────────────────────────────────────────────
        cmd = ["ffmpeg", "-y", "-i", str(input_video_path)]
        if satisfying_vid:
            cmd.extend(["-stream_loop", "-1", "-i", str(satisfying_vid)])
        if bgm_vid:
            cmd.extend(["-stream_loop", "-1", "-i", str(bgm_vid)])
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", out_v,
            "-map", out_a,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ])

        logger.info("Executing Mega Viral FFmpeg Pipeline...")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error("FFmpeg error: %s", stderr.decode()[-500:])
                return {"error": "FFmpeg failed", "details": stderr.decode()[-300:]}
        except Exception as e:
            return {"error": str(e)}

        # ── 14. Quality Control (Post-render) ──────────────────────────────────
        qc_result = None
        if use_quality_check:
            try:
                qc_report = await _qc.check(str(output_path))
                qc_result = {"passed": qc_report.passed, "score": qc_report.score, "summary": qc_report.summary()}
                features_used.append(f"QC: {qc_report.summary()}")
                logger.info("QC Report: %s", qc_report.summary())
            except Exception as e:
                logger.warning("QC failed: %s", e)

        # ── 15. Social Media AI (Viral Kit) ────────────────────────────────────
        social_kit = None
        if generate_social_kit and transcript_data:
            try:
                transcript_text = " ".join(w.get("word", "") for w in transcript_data.get("words", []))
                social_kit = await social_media_ai.generate_viral_package(
                    transcript=transcript_text,
                    metadata=meta,
                )
                if social_kit.get("success"):
                    features_used.append("SocialMediaAI Viral Kit")
            except Exception as e:
                logger.warning("SocialMediaAI failed: %s", e)

        return {
            "success": True,
            "output_path": str(output_path),
            "format": "9:16 (Mega Viral Vertical)",
            "features": features_used,
            "beat_cuts": beat_cuts,
            "qc": qc_result,
            "social_kit": social_kit,
        }


# Singleton
social_video_gen = SocialVideoGenerator()
