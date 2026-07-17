"""
Otonom Master Pipeline v3 (Moduler AI Fabrika)
───────────────────────────────────────────────
Tek bir URL ile tam veya parcacik pipeline calistirilabilir.

Pipeline Modlari:
  - full      : Indir → Transkripsiyon → LLM → Kes → Analiz → Render → Thumbnail → Medya Kit
  - download  : Sadece indir
  - analyze   : Indir + Transkripsiyon + LLM + Analiz (render yok)
  - render    : Mevcut klipleri yeniden render et
  - export    : Mevcut klipleri farkli formatlarda export et

Export Formatlari:
  - social    : 9:16 TikTok/Reels/Shorts (varsayilan)
  - landscape : 16:9 YouTube formatinda
  - raw       : Ham klipler (render yok)
  - custom    : Kullanici tanimli FFmpeg parametreleri
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional

from services.youtube_downloader import youtube_downloader
from services.faster_whisper_service import faster_whisper
from services.llm_reasoner import llm_reasoner
from services.social_video_generator import social_video_gen
from services.action_recognizer import action_recognizer
from services.thumbnail_generator import thumbnail_generator
from services.scene_detection import SceneDetectionEngine
from services.social_media_ai import social_media_ai
from services.emotion_detector import emotion_detector
from services.kick_archive import TARGET_CHANNEL_URL, is_target_vod_url

logger = logging.getLogger("master_pipeline")
_scene_detect = SceneDetectionEngine()


# ─── Export Formatlari ──────────────────────────────────────────────────────

EXPORT_FORMATS = {
    "social": {
        "label": "TikTok / Reels / Shorts (9:16)",
        "width": 1080,
        "height": 1920,
        "use_viral_editor": True,
    },
    "landscape": {
        "label": "YouTube (16:9)",
        "width": 1920,
        "height": 1080,
        "use_viral_editor": True,
    },
    "raw": {
        "label": "Ham Klip (render yok)",
        "width": 0,
        "height": 0,
        "use_viral_editor": False,
    },
    "short": {
        "label": "Kisa Klip (60sn siniri)",
        "max_duration": 60,
        "use_viral_editor": True,
    },
}


@dataclass
class PipelineConfig:
    """Pipeline konfigürasyonu — her adim icin ayri ayri kontrol."""
    url: str = ""
    mode: str = "full"
    export_format: str = "social"
    max_clips: int = 5
    game: str = "Kick"
    streamer: str = "Tuncay"
    custom_ffmpeg: Optional[str] = None

    # Adim bayraklari — hangi adimlar calissin
    do_download: bool = True
    do_transcribe: bool = True
    do_llm_clips: bool = True
    do_analyze: bool = True
    do_render: bool = True
    do_thumbnail: bool = True
    do_media_kit: bool = True

    # Render secenekleri
    use_brainrot: bool = True
    use_bgm: bool = True
    use_auto_zoom: bool = True
    use_ai_denoise: bool = True
    use_auto_censor: bool = True
    inject_emojis: bool = True
    use_beat_sync: bool = True
    use_effects: bool = True
    use_stickers: bool = True
    use_quality_check: bool = True

    def apply_mode(self):
        """Mode degerine gore adim bayraklarini ayarla."""
        if self.mode == "download":
            self.do_download = True
            self.do_transcribe = False
            self.do_llm_clips = False
            self.do_analyze = False
            self.do_render = False
            self.do_thumbnail = False
            self.do_media_kit = False
        elif self.mode == "analyze":
            self.do_download = True
            self.do_transcribe = True
            self.do_llm_clips = True
            self.do_analyze = True
            self.do_render = False
            self.do_thumbnail = False
            self.do_media_kit = False
        elif self.mode == "export":
            self.do_download = False
            self.do_transcribe = False
            self.do_llm_clips = False
            self.do_analyze = False
            self.do_render = True
            self.do_thumbnail = True
            self.do_media_kit = True
        # "full" => her sey acik (varsayilan)

    def apply_export_format(self):
        """Export formatina gore render seceneklerini ayarla."""
        fmt = EXPORT_FORMATS.get(self.export_format, EXPORT_FORMATS["social"])
        if self.export_format == "raw":
            self.do_render = False
        elif self.export_format == "short":
            self.max_clips = min(self.max_clips, 3)


# ─── Pipeline Sonuc ─────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    success: bool = False
    message: str = ""
    source_vod: str = ""
    total_clips: int = 0
    generated_clips: List[Dict[str, Any]] = field(default_factory=list)
    download_path: str = ""
    transcripts: Optional[Dict] = None
    semantic_clips: Optional[List] = None
    scored_clips: Optional[List] = None
    error: str = ""
    pipeline_mode: str = ""
    export_format: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "source_vod": self.source_vod,
            "total_clips": self.total_clips,
            "generated_clips": self.generated_clips,
            "download_path": self.download_path,
            "error": self.error,
            "pipeline_mode": self.pipeline_mode,
            "export_format": self.export_format,
        }


class MasterPipeline:
    def __init__(self):
        self.temp_dir = Path("data/temp_clips")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir = Path("data/social_exports")
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.clips_dir = Path("data/raw_clips")
        self.clips_dir.mkdir(parents=True, exist_ok=True)

    def get_export_formats(self) -> Dict[str, str]:
        """Desteklenen export formatlarini dondur."""
        return {k: v["label"] for k, v in EXPORT_FORMATS.items()}

    def get_download_strategies(self) -> list:
        """Mevcut indirme stratejilerini dondur."""
        return youtube_downloader.get_strategies()

    async def _slice_video(self, input_video: str, start: float, end: float, index: int) -> str:
        """Uzun yayindan belirtilen kesimi FFmpeg ile kopyalayip ayirir."""
        out_path = self.temp_dir / f"{Path(input_video).stem}_clip_{index}.mp4"
        dur = max(1.0, end - start)
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(input_video),
            "-t", str(dur),
            "-c:v", "copy", "-c:a", "copy",
            str(out_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        return str(out_path)

    async def _export_clip(self, input_path: str, fmt: str, custom_ffmpeg: Optional[str] = None) -> str:
        """Klip'i belirtilen formata export et."""
        if fmt == "raw" or fmt not in EXPORT_FORMATS:
            return input_path

        spec = EXPORT_FORMATS[fmt]
        w, h = spec.get("width", 1920), spec.get("height", 1080)
        max_dur = spec.get("max_duration")

        out_path = str(self.export_dir / f"{Path(input_path).stem}_{fmt}.mp4")

        if custom_ffmpeg:
            cmd_parts = ["ffmpeg", "-y", "-i", input_path] + custom_ffmpeg.split() + [out_path]
        else:
            filters = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
            cmd_parts = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-vf", filters,
                "-c:v", "libx264", "-crf", "23",
                "-c:a", "aac",
            ]
            if max_dur:
                cmd_parts += ["-t", str(max_dur)]
            cmd_parts.append(out_path)

        proc = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        if Path(out_path).exists():
            return out_path
        return input_path

    async def process_url(self, url: str, config: Optional[PipelineConfig] = None, **kwargs) -> Dict[str, Any]:
        """
        Pipeline ana giris noktu.
        Eski API uyumlulugu icin **kwargs destegi var.
        """
        if config is None:
            config = PipelineConfig(url=url, **kwargs)
        else:
            config.url = url or config.url

        config.apply_mode()
        config.apply_export_format()

        if not is_target_vod_url(config.url):
            return {
                "success": False,
                "error": f"Bu pipeline sadece {TARGET_CHANNEL_URL}/videos/... URL'lerini isler.",
            }

        logger.info("=== MASTER PIPELINE v3 [%s, fmt=%s] BASLATILDI: %s ===",
                     config.mode, config.export_format, config.url)

        result = PipelineResult(
            pipeline_mode=config.mode,
            export_format=config.export_format,
        )

        # ─── Adim 1: Indirme ──────────────────────────────────────────────
        vod_path = ""
        vod_duration = 3600.0

        if config.do_download:
            logger.info("Adim 1 — VOD indiriliyor...")
            dl_res = await youtube_downloader.download_video(config.url)
            if not dl_res.get("success"):
                result.error = f"Indirme basarisiz: {dl_res.get('error')}"
                return result.to_dict()
            vod_path = dl_res["file_path"]
            vod_duration = dl_res.get("duration", 3600)
            result.download_path = vod_path
            result.source_vod = dl_res.get("title", "")
            logger.info("VOD indirildi: %s (%.0f sn)", dl_res.get("title"), vod_duration)
        else:
            result.message = "Download atlandi (mod: export)"
            return result.to_dict()

        if config.mode == "download":
            result.success = True
            result.message = f"VOD indirildi: {vod_path}"
            result.total_clips = 0
            return result.to_dict()

        # ─── Adim 2: Transkripsiyon ───────────────────────────────────────
        words = []
        if config.do_transcribe:
            logger.info("Adim 2 — Faster-Whisper ile transkripsiyon...")
            transcript = await faster_whisper.transcribe(vod_path, word_timestamps=True)
            if not transcript.get("success"):
                result.error = "Transkripsiyon basarisiz."
                return result.to_dict()
            words = transcript.get("data", {}).get("words", [])

        text_for_llm = " ".join(f"[{w['start']:.1f}] {w['word']}" for w in words)

        # ─── Adim 3: LLM Semantic Highlight ───────────────────────────────
        semantic_clips = []
        if config.do_llm_clips and text_for_llm:
            logger.info("Adim 3 — Llama-3 viral anlari tespit ediyor...")
            semantic_clips = await llm_reasoner.get_semantic_highlights(text_for_llm)
            if not semantic_clips:
                logger.warning("LLM klip bulamadi — Fallback: her 60sn'de bir.")
                semantic_clips = [
                    {"start": i * 60.0, "end": min((i + 1) * 60.0, vod_duration)}
                    for i in range(min(config.max_clips, int(vod_duration // 60)))
                ]

        semantic_clips = semantic_clips[:config.max_clips]
        result.semantic_clips = semantic_clips
        logger.info("%d potansiyel viral an bulundu.", len(semantic_clips))

        # ─── Adim 4: Kes + Analiz ─────────────────────────────────────────
        scored_clips = []
        sliced_paths: list[str] = []

        if config.do_analyze or config.do_render:
            logger.info("Adim 4 — Klipler kesiliyor...")
            for idx, clip in enumerate(semantic_clips):
                p = await self._slice_video(vod_path, clip.get("start", 0), clip.get("end", 60), idx)
                sliced_paths.append(p)

        if config.do_analyze:
            logger.info("Adim 4b — YOLOv8 + SceneDetect + Emotion analiz...")
            analysis_tasks = [
                asyncio.gather(
                    action_recognizer.calculate_action_score(p),
                    _scene_detect.detect_scenes(p),
                    emotion_detector.analyze_video_emotions(p, sample_fps=0.3),
                    return_exceptions=True,
                )
                for p in sliced_paths
            ]
            analysis_results = await asyncio.gather(*analysis_tasks)

            for idx, ((yolo_res, scene_res, emotion_res), clip, sliced_path) in enumerate(
                zip(analysis_results, semantic_clips, sliced_paths)
            ):
                action_score = yolo_res.get("avg_objects_per_frame", 0) if isinstance(yolo_res, dict) else 0
                scene_count = scene_res.total_scenes if hasattr(scene_res, "total_scenes") else 0
                emotion_bonus = 0.0
                emotion_label = "neutral"
                if isinstance(emotion_res, dict) and emotion_res.get("success"):
                    spikes = emotion_res.get("viral_spikes", [])
                    if spikes:
                        emotion_bonus = max(s["viral_weight"] for s in spikes)
                        emotion_label = spikes[0]["emotion"]

                viral_score = round(action_score * 10 + scene_count * 0.5 + emotion_bonus * 5, 2)
                scored_clips.append({
                    "idx": idx, "clip": clip, "sliced_path": sliced_path,
                    "action_score": action_score, "scene_count": scene_count,
                    "emotion": emotion_label, "emotion_bonus": emotion_bonus,
                    "viral_score": viral_score, "reason": clip.get("reason", ""),
                })
            scored_clips.sort(key=lambda x: x["viral_score"], reverse=True)
            result.scored_clips = scored_clips
            logger.info("Skorlama tamam. En viral: #%.2f", scored_clips[0]["viral_score"] if scored_clips else 0)

        elif sliced_paths:
            for idx, clip in enumerate(semantic_clips):
                scored_clips.append({
                    "idx": idx, "clip": clip, "sliced_path": sliced_paths[idx],
                    "viral_score": 0, "reason": clip.get("reason", ""),
                })

        # ─── Adim 5-7: Render + Thumbnail + Medya Kit ─────────────────────
        final_videos: list[dict] = []

        for rank, sc in enumerate(scored_clips):
            idx = sc["idx"]
            sliced_path = sc["sliced_path"]
            clip = sc["clip"]

            # Render
            if config.do_render:
                logger.info("Adim 5 — Klip %d/%d render ediliyor (fmt=%s)...",
                            rank + 1, len(scored_clips), config.export_format)

                fmt_spec = EXPORT_FORMATS.get(config.export_format, EXPORT_FORMATS["social"])

                if fmt_spec.get("use_viral_editor"):
                    clip_transcript = await faster_whisper.transcribe(sliced_path, word_timestamps=True)
                    final_res = await social_video_gen.generate_viral_video(
                        input_video_path=sliced_path,
                        transcript_data=clip_transcript.get("data"),
                        facecam_position="auto",
                        remove_silences=True,
                        use_brainrot=config.use_brainrot,
                        use_bgm=config.use_bgm,
                        use_auto_zoom=config.use_auto_zoom,
                        use_ai_denoise=config.use_ai_denoise,
                        use_auto_censor=config.use_auto_censor,
                        inject_emojis=config.inject_emojis,
                        use_beat_sync=config.use_beat_sync,
                        use_scene_detect=False,
                        use_effects=config.use_effects,
                        use_stickers=config.use_stickers,
                        use_quality_check=config.use_quality_check,
                        generate_social_kit=config.do_media_kit,
                        metadata={"game": config.game, "streamer": config.streamer},
                    )
                    if not final_res.get("success"):
                        logger.error("Klip %d render basarisiz: %s", idx, final_res.get("error"))
                        continue
                else:
                    final_res = {"success": True, "output_path": sliced_path}

                final_res["rank"] = rank + 1
                final_res["viral_score"] = sc.get("viral_score", 0)
                final_videos.append(final_res)
            else:
                final_videos.append({
                    "success": True, "output_path": sliced_path,
                    "rank": rank + 1, "viral_score": sc.get("viral_score", 0),
                })

        # Thumbnail
        if config.do_thumbnail and final_videos:
            for fv in final_videos:
                if not fv.get("output_path"):
                    continue
                try:
                    thumb = await thumbnail_generator.generate_thumbnail(
                        video_path=fv["output_path"],
                        title="VIRAL",
                        timestamp=0,
                    )
                    fv["thumbnail_path"] = thumb
                except Exception:
                    pass

        # Medya Kit
        if config.do_media_kit and final_videos:
            for rank, fv in enumerate(final_videos):
                if not fv.get("output_path"):
                    continue
                txt_path = str(fv["output_path"]).replace(".mp4", "_MEDYAKIT.txt")
                sc = scored_clips[rank] if rank < len(scored_clips) else {}
                try:
                    kit = social_video_gen.generate_social_media_kit(
                        fv.get("output_path", ""),
                        game=config.game, streamer=config.streamer,
                    ) if hasattr(social_video_gen, "generate_social_media_kit") else {}
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(f"VIRAL KLIP #{rank + 1}\n")
                        f.write(f"Viral Skor: {sc.get('viral_score', 0):.2f}\n")
                        if kit:
                            f.write(json.dumps(kit, ensure_ascii=False, indent=2))
                    fv["media_kit_path"] = txt_path
                except Exception:
                    pass

        result.success = True
        result.total_clips = len(final_videos)
        result.generated_clips = final_videos
        result.message = f"{len(final_videos)} klip uretildi (mod={config.mode}, fmt={config.export_format})"
        logger.info("=== PIPELINE TAMAMLANDI: %d klip ===", len(final_videos))
        return result.to_dict()


master_pipeline = MasterPipeline()
