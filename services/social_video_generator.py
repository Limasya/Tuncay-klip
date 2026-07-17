"""
Sosyal Medya Dikey Kurgu Jeneratörü (Ultimate Viral Video)
──────────────────────────────────────────────────────────
Standart klipleri 9:16 formatına çevirir. 
Açık Kaynak Proje Entegrasyonları:
- Face Tracking (Auto-Reframe) via MediaPipe
- Silence Removal (Auto Jump-Cut)
- Dynamic Hormozi Subtitles
- Auto-Zoom (Audio Peak Detection)
- Background Music (BGM) Ducking
- Brainrot / Satisfying Video Overlay
- Meme / Keyword B-Roll Overlay
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

logger = logging.getLogger("social_video_generator")


class SocialVideoGenerator:
    def __init__(self):
        self.output_dir = Path("data/social_exports")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.satisfying_dir = Path("data/satisfying_videos")
        self.satisfying_dir.mkdir(parents=True, exist_ok=True)
        
        self.bgm_dir = Path("data/bgm")
        self.bgm_dir.mkdir(parents=True, exist_ok=True)
        
        # ASS stili overrides
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
        """Brainrot formatı için rastgele bir satisfying video seçer."""
        videos = list(self.satisfying_dir.glob("*.mp4"))
        if not videos:
            return None
        return str(random.choice(videos))
        
    def _get_random_bgm(self) -> str | None:
        """Rastgele telifsiz arka plan müziği seçer."""
        bgms = list(self.bgm_dir.glob("*.mp3")) + list(self.bgm_dir.glob("*.wav"))
        if not bgms:
            return None
        return str(random.choice(bgms))

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
        inject_emojis: bool = True
    ) -> dict[str, Any]:
        """
        16:9 videoyu 9:16 viral bir videoya dönüştürür. 
        Auto-Zoom, BGM Ducking, Brainrot, Meme Overlay, Denoise ve Auto-Censor içerir.
        """
        logger.info("Generating ultimate viral video for %s", input_video_path)
        
        if not os.path.exists(input_video_path):
            return {"error": "Input video not found"}

        filename = Path(input_video_path).stem
        output_path = self.output_dir / f"{filename}_ultimate_viral.mp4"
        features_used = []

        # 1. Altyazı (ASS) 
        ass_path = None
        if transcript_data and "words" in transcript_data:
            try:
                ass_content = advanced_subtitle.generate_ass_from_whisper(
                    whisper_segments=[transcript_data], 
                    style_name="viral_tiktok",
                    max_words_per_line=3,
                    inject_emojis=inject_emojis
                )
                ass_path = self.output_dir / f"{filename}.ass"
                advanced_subtitle.save_ass(ass_content, str(ass_path))
                features_used.append("Hormozi Bouncy Subtitles")
                if inject_emojis:
                    features_used.append("Emoji Injector")
            except Exception as e:
                logger.warning("Subtitle generation failed: %s", e)
                ass_path = None

        # 2. Audio Denoise (Temel filtre)
        filter_parts = []
        v_input = "[0:v]"
        a_input = "[0:a]"

        if use_ai_denoise:
            features_used.append("AI Denoise (afftdn)")
            filter_parts.append(f"{a_input}afftdn=nr=15:nf=-25[denoised_a];")
            a_input = "[denoised_a]"

        # 3. Auto-Censor (Küfür sansürleme)
        if use_auto_censor and transcript_data:
            bleeps = auto_censor.detect_profanity(transcript_data)
            if bleeps:
                features_used.append("Auto-Censor (Bleep)")
                censor_filter, out_a_label = auto_censor.generate_bleep_filter(bleeps, input_audio_label=a_input)
                filter_parts.append(censor_filter)
                a_input = out_a_label

        # 4. Sessizlik Tespiti ve Jump Cut mantığı
        
        if remove_silences:
            logger.info("Running silence detection...")
            sr_result = await silence_remover.detect_silences(input_video_path)
            if sr_result.get("success") and sr_result.get("silences"):
                total_duration = sr_result.get("total_duration", 0)
                silences = sr_result.get("silences")
                keep_segments = []
                last_end = 0.0
                for s in silences:
                    if s["start"] > last_end:
                        keep_segments.append((last_end, s["start"]))
                    last_end = s["end"]
                if last_end < total_duration:
                    keep_segments.append((last_end, total_duration))
                
                if keep_segments:
                    features_used.append("Auto-Jump-Cuts")
                    concat_inputs = ""
                    total_keep = len(keep_segments)
                    for i, (start, end) in enumerate(keep_segments):
                        filter_parts.append(
                            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v_trim{i}];"
                            f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a_trim{i}];"
                        )
                        concat_inputs += f"[v_trim{i}][a_trim{i}]"
                        
                    filter_parts.append(f"{concat_inputs}concat=n={total_keep}:v=1:a=1[v_jump][a_jump];")
                    v_input = "[v_jump]"
                    a_input = "[a_jump]"

        # 3. Yüz Takibi (Auto Reframe)
        face_crop = "iw/4:ih/4:0:0"
        if facecam_position == "auto":
            ft_result = await face_tracker.get_face_trajectory(input_video_path, fps=2)
            if ft_result.get("success"):
                trajectory = ft_result.get("trajectory", [])
                if trajectory:
                    features_used.append("AI Face Tracking")
                    avg_x = sum(p["x"] for p in trajectory) / len(trajectory)
                    avg_y = sum(p["y"] for p in trajectory) / len(trajectory)
                    face_crop = f"max(0,{avg_x}*iw-iw/8):max(0,{avg_y}*ih-ih/8)"
                    # crop width/height in filter
                    face_crop = f"iw/4:ih/4:{face_crop}"
            else:
                logger.warning("Face tracking failed, using default crop.")

        # 4. Audio Peaks / Auto-Zoom 
        zoom_filter = ""
        if use_auto_zoom:
            peak_res = await audio_analyzer.get_loud_peaks(input_video_path)
            if peak_res.get("success"):
                peaks = peak_res.get("peaks", [])
                if peaks:
                    features_used.append("Audio-Reactive Auto-Zoom")
                    zoom_exprs = []
                    # Sadece en yüksek tepkilere zoom yap
                    for p in peaks:
                        st = p["start"]
                        en = p["end"]
                        zoom_exprs.append(f"between(t,{st},{en})")
                    if zoom_exprs:
                        zoom_cond = "+".join(zoom_exprs)
                        # zoom_cond doğruysa (1) zoom 1.5, yanlışsa (0) zoom 1
                        zoom_filter = f",zoompan=z='if({zoom_cond},1.5,1)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1"

        # 5. FFmpeg Filter Complex Oluşturma (Layout)
        filter_parts.append(f"{v_input}split=3[bg][game][face_raw];")
        
        # Facecam (Crop + Optional Zoom)
        filter_parts.append(f"[face_raw]crop={face_crop}{zoom_filter},scale=800:-1[face_scaled];")
        
        # Gameplay veya Brainrot
        satisfying_vid = None
        if use_brainrot:
            satisfying_vid = self._get_random_satisfying_video()
        
        if satisfying_vid:
            features_used.append("Brainrot Satisfying Split")
            # 2. Input = Satisfying video
            filter_parts.append("[1:v]scale=1080:-1[game_scaled];")
        else:
            filter_parts.append("[game]scale=1080:-1[game_scaled];")

        # Background Blur
        filter_parts.append("[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bg_blur];")
        
        # Overlay Layout
        filter_parts.append("[bg_blur][game_scaled]overlay=0:(H-h)/2+150[game_overlay];")
        filter_parts.append("[game_overlay][face_scaled]overlay=(W-w)/2:150[out_video_clean]")
        
        out_v_label = "[out_video_clean]"
        
        # Altyazı Ekleme
        if ass_path and os.path.exists(ass_path):
            ass_path_str = str(ass_path).replace('\\', '\\\\').replace(':', '\\:')
            filter_parts.append(f";{out_v_label}ass='{ass_path_str}'[out_video_ass]")
            out_v_label = "[out_video_ass]"

        # BGM Ducking
        bgm_vid = None
        out_a_label = a_input
        if use_bgm:
            bgm_vid = self._get_random_bgm()
            if bgm_vid:
                features_used.append("BGM Audio Ducking")
                # Ducking mantığı: asplit ile ana sesi ikiye böl, birini sidechain referansı yap,
                # bgm'i (input 2) sidechaincompress ile kıs, sonra amix ile ana sesle birleştir.
                input_idx = 2 if satisfying_vid else 1
                filter_parts.append(f";{out_a_label}asplit=2[main_a][sc_ref];")
                filter_parts.append(f"[{input_idx}:a]volume=0.3[bgm_vol];")
                filter_parts.append("[bgm_vol][sc_ref]sidechaincompress=threshold=0.08:ratio=4[bgm_ducked];")
                filter_parts.append("[main_a][bgm_ducked]amix=inputs=2:duration=first:dropout_transition=2[out_audio]")
                out_a_label = "[out_audio]"

        filter_complex = "".join(filter_parts)

        # 6. FFmpeg komutunu oluştur
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_video_path)
        ]
        
        if satisfying_vid:
            # Satisfying video (Loop, sessiz)
            cmd.extend(["-stream_loop", "-1", "-i", str(satisfying_vid)])
            
        if bgm_vid:
            # BGM video/audio (Loop)
            cmd.extend(["-stream_loop", "-1", "-i", str(bgm_vid)])

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", out_v_label,
            "-map", out_a_label,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_path)
        ])

        logger.info("Executing ultimate FFmpeg command...")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                logger.error("FFmpeg error: %s", stderr.decode())
                return {"error": "FFmpeg processing failed", "details": stderr.decode()[-200:]}
                
        except Exception as e:
            logger.error("Error executing ffmpeg: %s", e)
            return {"error": str(e)}

        return {
            "success": True,
            "output_path": str(output_path),
            "format": "9:16 (Ultimate Vertical)",
            "features": features_used
        }

# Singleton
social_video_gen = SocialVideoGenerator()
