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
from services.thumbnail_generator import thumbnail_generator
from services.scene_detection import SceneDetectionEngine
from services.social_media_ai import social_media_ai
from services.ai_critic import ai_critic
from services.critic_analytics import critic_analytics
from services.kick_archive import TARGET_CHANNEL_URL, is_target_vod_url
from shared.utils.video_processor import video_processor
from services.ai_analysis import ai_analyzer

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

    # AI Critic — kapalı döngü kalite kontrolü (5 boyutlu)
    use_ai_critic: bool = True
    critic_target_score: float = 8.5
    critic_max_rounds: int = 3          # ilk render + en fazla 3 düzeltme turu
    critic_autofix_hook: bool = True    # açılış/hook auto-fix
    critic_autofix_subtitle: bool = True  # altyazı boyut auto-fix
    critic_autofix_zoom: bool = True     # zoom timing auto-fix
    critic_autofix_cut: bool = True      # kesim noktası auto-fix

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
        """Uzun yayindan belirtilen kesimi Rust binary veya FFmpeg ile kopyalayip ayirir."""
        out_path = self.temp_dir / f"{Path(input_video).stem}_clip_{index}.mp4"
        dur = max(1.0, end - start)

        if video_processor.available:
            result = await video_processor.clip(
                input_path=input_video,
                output_path=str(out_path),
                start=start,
                duration=dur,
            )
            if result.get("success"):
                return str(out_path)
            logger.warning("Rust clip failed, falling back to FFmpeg: %s", result.get("error"))

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
        """Klip'i belirtilen formata export et — Rust binary veya FFmpeg."""
        if fmt == "raw" or fmt not in EXPORT_FORMATS:
            return input_path

        spec = EXPORT_FORMATS[fmt]
        w, h = spec.get("width", 1920), spec.get("height", 1080)
        max_dur = spec.get("max_duration")

        out_path = str(self.export_dir / f"{Path(input_path).stem}_{fmt}.mp4")

        platform_map = {"social": "tiktok", "landscape": "youtube", "landscape_wide": "youtube"}
        platform = platform_map.get(fmt)

        if video_processor.available and platform and not custom_ffmpeg:
            vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
            if max_dur:
                vf += f",trim=duration={max_dur}"
                vf += ",setpts=PTS-STARTPTS"
            result = await video_processor.export(
                input_path=input_path,
                output_path=out_path,
                platform=platform,
                filter=vf,
            )
            if result.get("success"):
                return out_path
            logger.warning("Rust export failed, falling back to FFmpeg: %s", result.get("error"))

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

    async def _batch_slice_videos(
        self, input_video: str, clips: List[Dict[str, Any]], max_jobs: int = 4
    ) -> List[str]:
        """Rust batch komutuyla toplu klip kesimi — parallel FFmpeg."""
        stem = Path(input_video).stem
        paths = [
            str(self.temp_dir / f"{stem}_clip_{i}.mp4")
            for i in range(len(clips))
        ]

        if video_processor.available and len(clips) > 1:
            manifest_jobs = []
            for idx, clip in enumerate(clips):
                manifest_jobs.append({
                    "input": input_video,
                    "output": paths[idx],
                    "start": clip.get("start", 0),
                    "duration": max(1.0, clip.get("end", 60) - clip.get("start", 0)),
                })

            import json as _json
            manifest_path = str(self.temp_dir / f"{stem}_manifest.json")
            await asyncio.to_thread(
                Path(manifest_path).write_text,
                _json.dumps({"jobs": manifest_jobs}),
                "utf-8",
            )
            try:
                result = await video_processor.batch(
                    manifest_path=manifest_path,
                    output_dir=str(self.temp_dir),
                    jobs=max_jobs,
                )
                if result.get("success"):
                    logger.info("Batch slice tamamlandi: %d/%d klip",
                                result.get("succeeded", 0), result.get("total", 0))
                    return paths
                logger.warning("Batch slice basarisiz: %s", result.get("error"))
            except Exception as e:
                logger.warning("Batch slice hatasi: %s — fallback to sequential", e)

        for idx, clip in enumerate(clips):
            paths[idx] = await self._slice_video(
                input_video, clip.get("start", 0), clip.get("end", 60), idx
            )
        return paths

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
            if not transcript.get("text"):
                result.error = "Transkripsiyon basarisiz."
                return result.to_dict()
            words = transcript.get("words", [])

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
            logger.info("Adim 4 — Klipler kesiliyor (batch)...")
            sliced_paths = await self._batch_slice_videos(vod_path, semantic_clips)

        if config.do_analyze:
            logger.info("Adim 4b — Unified AI analiz (C++ signal + YOLO + Scene + Emotion)...")
            analyses = await ai_analyzer.analyze_vod(vod_path, semantic_clips)

            for idx, (clip, sliced_path) in enumerate(zip(semantic_clips, sliced_paths)):
                if idx < len(analyses):
                    a = analyses[idx]
                    scored_clips.append({
                        "idx": idx, "clip": clip, "sliced_path": sliced_path,
                        "action_score": a.video.action_score,
                        "scene_count": a.video.scene_count,
                        "emotion": a.emotion.dominant_emotion,
                        "emotion_bonus": a.emotion.viral_weight,
                        "cpp_bonus": a.score_breakdown.get("correlation", 0),
                        "bpm": a.audio.bpm,
                        "loud_peaks": a.audio.loud_peaks,
                        "viral_moments": [m.__dict__ for m in a.viral_moments],
                        "viral_score": a.viral_score,
                        "score_breakdown": a.score_breakdown,
                        "reason": clip.get("reason", ""),
                    })
                else:
                    scored_clips.append({
                        "idx": idx, "clip": clip, "sliced_path": sliced_path,
                        "viral_score": 0, "reason": clip.get("reason", ""),
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

        # ─── Adim 5-7: Render + AI Critic (kapalı döngü) + Thumbnail + Medya Kit ──
        final_videos: list[dict] = []

        # Renderer'da kullanılan altyazı font boyutunu critic'e ilet
        try:
            from services.advanced_subtitle import advanced_subtitle
            _vt = advanced_subtitle._styles.get("viral_tiktok")
            subtitle_fontsize = getattr(_vt, "fontsize", 24) if _vt else 24
        except Exception:
            subtitle_fontsize = 24

        for rank, sc in enumerate(scored_clips):
            idx = sc["idx"]
            sliced_path = sc["sliced_path"]
            clip = sc["clip"]

            fmt_spec = EXPORT_FORMATS.get(config.export_format, EXPORT_FORMATS["social"])

            # Render kapalı veya viral editor kullanılmayan formatlar → ham klip
            if not config.do_render or not fmt_spec.get("use_viral_editor"):
                final_videos.append({
                    "success": True, "output_path": sliced_path,
                    "rank": rank + 1, "viral_score": sc.get("viral_score", 0),
                })
                continue

            # ── Kapalı döngü: render → critic → multi-fix → yeniden render ──
            current_input = sliced_path
            best_res: Optional[dict] = None
            best_report = None
            round_idx = 0

            while True:
                logger.info("Adim 5 — Klip %d/%d render (tur %d, fmt=%s)...",
                            rank + 1, len(scored_clips), round_idx + 1, config.export_format)

                clip_transcript = await faster_whisper.transcribe(current_input, word_timestamps=True)
                final_res = await social_video_gen.generate_viral_video(
                    input_video_path=current_input,
                    transcript_data=clip_transcript,
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
                    break

                # AI Critic devre dışıysa tek render ile bitir
                if not config.use_ai_critic:
                    best_res = final_res
                    break

                report = await ai_critic.critique(
                    video_path=final_res.get("output_path", ""),
                    transcript_data=clip_transcript,
                    subtitle_fontsize=subtitle_fontsize,
                    subtitle_ass_path=final_res.get("subtitle_ass_path"),
                    metadata={"game": config.game, "streamer": config.streamer},
                )
                final_res["critique"] = report.to_dict()
                logger.info("Klip %d — %s", rank + 1, report.summary().replace("\n", " "))

                # ── A/B ölçümü için turu kaydet ──
                prev_scores = best_report.dimension_scores if best_report else None
                critic_analytics.record_round(
                    clip_id=f"clip_{rank}",
                    round_idx=round_idx,
                    video_path=final_res.get("output_path", ""),
                    dimension_scores=report.dimension_scores,
                    total_score=report.score,
                    applied_fixes=report.applied_fixes,
                    previous_scores=prev_scores,
                    passed=report.passed,
                )

                # En yüksek puanlı render'ı sakla
                if best_report is None or report.score > best_report.score:
                    best_res, best_report = final_res, report

                round_idx += 1
                # Durma koşulları
                if report.passed or round_idx > config.critic_max_rounds:
                    break
                # Hiçbir auto-fix aktif mi?
                any_autofix = (
                    config.critic_autofix_hook
                    or config.critic_autofix_subtitle
                    or config.critic_autofix_zoom
                    or config.critic_autofix_cut
                )
                if not any_autofix:
                    break
                # Düzeltilmeye değer sorun kaldı mı?
                fixable_dims = {i.dimension for i in report.issues} & {
                    d for d, enabled in [
                        ("opening", config.critic_autofix_hook),
                        ("subtitle", config.critic_autofix_subtitle),
                        ("zoom", config.critic_autofix_zoom),
                        ("cut", config.critic_autofix_cut),
                    ] if enabled
                }
                if not fixable_dims:
                    break

                # ── Multi-dimensional auto-fix uygula ──
                fixed_path, applied_fixes = await ai_critic.auto_fix(
                    video_path=current_input,
                    report=report,
                    subtitle_fontsize=subtitle_fontsize,
                    transcript_data=clip_transcript,
                    fix_round=round_idx,
                )
                if not fixed_path:
                    break
                current_input = fixed_path

            if best_res is None:
                continue
            best_res["rank"] = rank + 1
            best_res["viral_score"] = sc.get("viral_score", 0)
            if best_report is not None:
                best_res["critic_rounds"] = round_idx
            final_videos.append(best_res)

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
                except Exception as e:
                    logger.debug("Thumbnail üretilemedi: %s", e)

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
                except Exception as e:
                    logger.debug("Medya kit oluşturulamadı: %s", e)

        result.success = True
        result.total_clips = len(final_videos)
        result.generated_clips = final_videos
        result.message = f"{len(final_videos)} klip uretildi (mod={config.mode}, fmt={config.export_format})"
        logger.info("=== PIPELINE TAMAMLANDI: %d klip ===", len(final_videos))
        return result.to_dict()

    async def process_local(self, vod_path: str, config: Optional[PipelineConfig] = None, **kwargs) -> Dict[str, Any]:
        """Mevcut VOD dosyasını indirmeden doğrudan işle (transkripsiyon → LLM → render)."""
        if config is None:
            config = PipelineConfig(url="", **kwargs)
        config.do_download = False
        config.apply_export_format()

        from pathlib import Path as _P
        vod_file = _P(vod_path)
        if not vod_file.exists():
            return {"success": False, "error": f"Dosya bulunamadi: {vod_path}"}

        logger.info("=== PROCESS_LOCAL [fmt=%s] BASLATILDI: %s ===", config.export_format, vod_path)

        result = PipelineResult(pipeline_mode=config.mode, export_format=config.export_format)
        result.download_path = str(vod_file)
        result.source_vod = vod_file.stem

        # VOD suresi
        try:
            if video_processor.available:
                probe_result = await video_processor.probe(str(vod_file))
                vod_duration = float(
                    probe_result.get("format", {}).get("duration", 5196.0)
                ) if probe_result.get("success") else 5196.0
            else:
                probe = await asyncio.create_subprocess_exec(
                    "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                    "-of", "csv=p=0", str(vod_file),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                out, _ = await probe.communicate()
                vod_duration = float(out.decode().strip()) if out else 5196.0
        except Exception:
            vod_duration = 5196.0

        # Adim 2: Transkripsiyon
        words = []
        if config.do_transcribe:
            logger.info("Adim 2 — Faster-Whisper ile transkripsiyon...")
            transcript = await faster_whisper.transcribe(str(vod_file), word_timestamps=True)
            if not transcript.get("text"):
                result.error = "Transkripsiyon basarisiz."
                return result.to_dict()
            words = transcript.get("words", [])
            logger.info("Transkripsiyon tamamlandi: %d kelime", len(words))

        text_for_llm = " ".join(f"[{w['start']:.1f}] {w['word']}" for w in words)

        # Adim 3: LLM Semantic Highlight
        semantic_clips = []
        if config.do_llm_clips and text_for_llm:
            logger.info("Adim 3 — LLM viral anlari tespit ediyor...")
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

        # Adim 4: Kes + Analiz
        scored_clips = []
        sliced_paths: list[str] = []

        if config.do_analyze or config.do_render:
            logger.info("Adim 4 — Klipler kesiliyor (batch)...")
            sliced_paths = await self._batch_slice_videos(str(vod_file), semantic_clips)

        if config.do_analyze:
            logger.info("Adim 4b — Unified AI analiz...")
            analyses = await ai_analyzer.analyze_vod(str(vod_file), semantic_clips)

            for idx, (clip, sliced_path) in enumerate(zip(semantic_clips, sliced_paths)):
                if idx < len(analyses):
                    a = analyses[idx]
                    scored_clips.append({
                        "idx": idx, "clip": clip, "sliced_path": sliced_path,
                        "action_score": a.video.action_score,
                        "scene_count": a.video.scene_count,
                        "emotion": a.emotion.dominant_emotion,
                        "emotion_bonus": a.emotion.viral_weight,
                        "cpp_bonus": a.score_breakdown.get("correlation", 0),
                        "bpm": a.audio.bpm,
                        "loud_peaks": a.audio.loud_peaks,
                        "viral_moments": [m.__dict__ for m in a.viral_moments],
                        "viral_score": a.viral_score,
                        "score_breakdown": a.score_breakdown,
                        "reason": clip.get("reason", ""),
                    })
                else:
                    scored_clips.append({
                        "idx": idx, "clip": clip, "sliced_path": sliced_path,
                        "viral_score": 0, "reason": clip.get("reason", ""),
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

        # Adim 5-7: Render
        final_videos: list[dict] = []
        try:
            from services.advanced_subtitle import advanced_subtitle
            _vt = advanced_subtitle._styles.get("viral_tiktok")
            subtitle_fontsize = getattr(_vt, "fontsize", 24) if _vt else 24
        except Exception:
            subtitle_fontsize = 24

        for rank, sc in enumerate(scored_clips):
            idx = sc["idx"]
            sliced_path = sc["sliced_path"]
            clip = sc["clip"]

            fmt_spec = EXPORT_FORMATS.get(config.export_format, EXPORT_FORMATS["social"])

            if not config.do_render or not fmt_spec.get("use_viral_editor"):
                final_videos.append({
                    "success": True, "output_path": sliced_path,
                    "rank": rank + 1, "viral_score": sc.get("viral_score", 0),
                })
                continue

            current_input = sliced_path
            best_res: Optional[dict] = None
            best_report = None
            round_idx = 0

            while True:
                logger.info("Adim 5 — Klip %d/%d render (tur %d)...", rank + 1, len(scored_clips), round_idx + 1)
                clip_transcript = await faster_whisper.transcribe(current_input, word_timestamps=True)
                final_res = await social_video_gen.generate_viral_video(
                    input_video_path=current_input,
                    transcript_data=clip_transcript,
                    facecam_position="auto", remove_silences=True,
                    use_brainrot=config.use_brainrot, use_bgm=config.use_bgm,
                    use_auto_zoom=config.use_auto_zoom, use_ai_denoise=config.use_ai_denoise,
                    use_auto_censor=config.use_auto_censor, inject_emojis=config.inject_emojis,
                    use_beat_sync=config.use_beat_sync, use_scene_detect=False,
                    use_effects=config.use_effects, use_stickers=config.use_stickers,
                    use_quality_check=config.use_quality_check,
                    generate_social_kit=config.do_media_kit,
                    metadata={"game": config.game, "streamer": config.streamer},
                )
                if not final_res.get("success"):
                    logger.error("Klip %d render basarisiz: %s", idx, final_res.get("error"))
                    break

                if not config.use_ai_critic:
                    best_res = final_res
                    break

                report = await ai_critic.critique(
                    video_path=final_res.get("output_path", ""),
                    transcript_data=clip_transcript,
                    subtitle_fontsize=subtitle_fontsize,
                    subtitle_ass_path=final_res.get("subtitle_ass_path"),
                    metadata={"game": config.game, "streamer": config.streamer},
                )
                final_res["critique"] = report.to_dict()
                logger.info("Klip %d — %s", rank + 1, report.summary().replace("\n", " "))

                prev_scores = best_report.dimension_scores if best_report else None
                critic_analytics.record_round(
                    clip_id=f"clip_{rank}", round_idx=round_idx,
                    video_path=final_res.get("output_path", ""),
                    dimension_scores=report.dimension_scores,
                    total_score=report.score, applied_fixes=report.applied_fixes,
                    previous_scores=prev_scores, passed=report.passed,
                )

                if best_report is None or report.score > best_report.score:
                    best_res, best_report = final_res, report

                round_idx += 1
                if report.passed or round_idx > config.critic_max_rounds:
                    break
                any_autofix = (config.critic_autofix_hook or config.critic_autofix_subtitle
                               or config.critic_autofix_zoom or config.critic_autofix_cut)
                if not any_autofix:
                    break
                fixable_dims = {i.dimension for i in report.issues} & {
                    d for d, enabled in [
                        ("opening", config.critic_autofix_hook),
                        ("subtitle", config.critic_autofix_subtitle),
                        ("zoom", config.critic_autofix_zoom),
                        ("cut", config.critic_autofix_cut),
                    ] if enabled
                }
                if not fixable_dims:
                    break
                fixed_path, applied_fixes = await ai_critic.auto_fix(
                    video_path=current_input, report=report,
                    subtitle_fontsize=subtitle_fontsize,
                    transcript_data=clip_transcript,
                    fix_round=round_idx,
                )
                if not fixed_path:
                    break
                current_input = fixed_path

            if best_res is None:
                continue
            best_res["rank"] = rank + 1
            best_res["viral_score"] = sc.get("viral_score", 0)
            if best_report is not None:
                best_res["critic_rounds"] = round_idx
            final_videos.append(best_res)

        # Thumbnail
        if config.do_thumbnail and final_videos:
            for fv in final_videos:
                if not fv.get("output_path"):
                    continue
                try:
                    thumb = await thumbnail_generator.generate_thumbnail(
                        video_path=fv["output_path"], title="VIRAL", timestamp=0,
                    )
                    fv["thumbnail_path"] = thumb
                except Exception as e:
                    logger.debug("Thumbnail uretilemedi: %s", e)

        result.success = True
        result.total_clips = len(final_videos)
        result.generated_clips = final_videos
        result.message = f"{len(final_videos)} klip uretildi (process_local, fmt={config.export_format})"
        logger.info("=== PROCESS_LOCAL TAMAMLANDI: %d klip ===", len(final_videos))
        return result.to_dict()

    # ─── STREAM MODE: Indirmeden HLS uzerinden isleme ────────────────────────

    async def _get_hls_source_url(self, kick_url: str) -> Optional[Dict[str, Any]]:
        """Kick VOD URL'sinden HLS source URL'yi curl_cffi ile al (indirmeden)."""
        import re
        from config import get_settings
        settings = get_settings()
        slug = settings.kick_channel_slug
        video_slug = kick_url.rstrip("/").split("/")[-1]
        api_url = f"https://kick.com/api/v2/channels/{slug}/videos?limit=50&sort=date"

        def _fetch():
            try:
                from curl_cffi.requests import Session as CurlSession
                session = CurlSession(impersonate="chrome124")
                resp = session.get(api_url, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                items = data if isinstance(data, list) else data.get("data") or data.get("videos") or []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item_slug = str(item.get("slug") or "")
                    item_id = str(item.get("id") or "")
                    if item_slug == video_slug or item_id == video_slug:
                        source = item.get("source", "")
                        title = item.get("session_title") or item.get("title") or "vod"
                        duration = item.get("duration") or 0
                        if source:
                            return {"source_url": source, "title": title, "duration": duration}
                return None
            except Exception as e:
                logger.warning("HLS source fetch failed: %s", e)
                return None

        return await asyncio.to_thread(_fetch)

    async def _stream_audio_from_hls_to_memory(self, hls_url: str) -> Optional[bytes]:
        """HLS URL'den sadece sesi memory'ye stream et (disk yok)."""
        cmd = [
            "ffmpeg", "-y",
            "-headers", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36\r\nReferer: https://kick.com/\r\n",
            "-i", hls_url,
            "-vn", "-ac", "1", "-ar", "16000", "-f", "wav",
            "pipe:1",
        ]
        logger.info("Streaming audio from HLS → memory (disk yok)...")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=1800)
        if proc.returncode != 0:
            logger.warning("HLS audio stream failed: %s", stderr.decode(errors="replace")[-300:] if stderr else "")
            return None
        if not stdout or len(stdout) < 1024:
            logger.warning("HLS audio stream empty (%d bytes)", len(stdout) if stdout else 0)
            return None
        logger.info("HLS audio stream tamamlandi: %.1f MB (memory)", len(stdout) / 1024 / 1024)
        return stdout

    async def _stream_segment_from_hls(self, hls_url: str, start: float, end: float, output_path: str) -> bool:
        """HLS URL'den belirli bir zamana ait video segmentini cek (indirmeden)."""
        dur = max(1.0, end - start)
        cmd = [
            "ffmpeg", "-y",
            "-headers", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36\r\nReferer: https://kick.com/\r\n",
            "-ss", str(start),
            "-i", hls_url,
            "-t", str(dur),
            "-c:v", "copy", "-c:a", "copy",
            "-movflags", "+faststart",
            output_path,
        ]
        logger.info("Streaming segment [%.1f - %.1f] from HLS...", start, end)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        if proc.returncode != 0:
            logger.warning("HLS segment failed: %s", stderr.decode(errors="replace")[-200:] if stderr else "")
            return False
        if not Path(output_path).exists():
            return False
        from services.youtube_downloader import CurlCffiFfmpegStrategy
        validator = CurlCffiFfmpegStrategy(Path("data/raw_vods"))
        v = validator._validate_mp4(output_path)
        if not v.get("valid"):
            logger.warning("Segment MP4 invalid: %s", v.get("error"))
            Path(output_path).unlink(missing_ok=True)
            return False
        return True

    async def process_stream(self, url: str, config: Optional[PipelineConfig] = None, **kwargs) -> Dict[str, Any]:
        """
        STREAM MODE: VOD'u indirmeden HLS uzerinden isle.
        
        Akis:
          1. Kick API'den HLS source URL al (curl_cffi, ~1KB)
          2. ffmpeg ile sadece sesi stream et → WAV (~50MB, ~30sn)
          3. Groq/faster-whisper ile transkripsiyon
          4. LLM ile viral anlari bul
          5. Her klip icin: sadece o segmenti HLS'den stream et → render
        
        Hiçbir zaman tam VOD'u indirmez. Sadece ihtiyac kadar bant genisligi.
        """
        if config is None:
            config = PipelineConfig(url=url, **kwargs)
        else:
            config.url = url or config.url
        config.apply_export_format()

        logger.info("=== PROCESS_STREAM [fmt=%s] BASLATILDI: %s ===", config.export_format, url)

        result = PipelineResult(pipeline_mode="stream", export_format=config.export_format)
        result.source_vod = url

        # ─── Adim 1: HLS source URL al ──────────────────────────────────
        hls_info = await self._get_hls_source_url(url)
        if not hls_info or not hls_info.get("source_url"):
            result.error = "Kick API'den HLS source URL alinamadi."
            return result.to_dict()

        hls_url = hls_info["source_url"]
        vod_title = hls_info.get("title", "unknown")
        vod_duration = hls_info.get("duration", 3600) or 3600
        result.source_vod = vod_title
        logger.info("HLS source alindi: %s (%.0f sn)", vod_title, vod_duration)

        # ─── Adim 2: Sadece sesi stream et → transkripsiyon (SIFIR DISK WRITE) ──
        words = []
        transcript_text = ""

        if config.do_transcribe:
            try:
                logger.info("Adim 2a — HLS'den ses cekiliyor (memory, disk yok)...")
                audio_bytes = await self._stream_audio_from_hls_to_memory(hls_url)
                if not audio_bytes:
                    result.error = "HLS'den ses cekilemedi."
                    logger.error("HLS audio stream basarisiz (memory)")
                    return result.to_dict()

                logger.info("Adim 2b — Ses hazir: %.1f MB, Groq Whisper'a gonderiliyor...", len(audio_bytes) / 1024 / 1024)

                # Groq Whisper'a memory'den gonder (25MB chunk splitting)
                transcript = await faster_whisper._transcribe_groq_from_bytes(audio_bytes, language="auto")
                if not transcript.get("text"):
                    result.error = "Transkripsiyon basarisiz."
                    logger.error("Transkripsiyon basarisiz (bos metin)")
                    return result.to_dict()

                words = transcript.get("words", [])
                transcript_text = transcript.get("text", "")
                logger.info("Adim 2c — Transkripsiyon tamamlandi: %d kelime, backend=%s, dil=%s, parca=%s",
                            len(words), transcript.get("backend"), transcript.get("language"), transcript.get("chunks", 1))
            except Exception as e:
                logger.error("Transkripsiyon hatasi: %s", e, exc_info=True)
                result.error = f"Transkripsiyon hatasi: {e}"
                return result.to_dict()
            finally:
                audio_bytes = None  # Memory'yi serbest birak

        text_for_llm = " ".join(f"[{w['start']:.1f}] {w['word']}" for w in words)

        # ─── Adim 3: LLM Semantic Highlight ──────────────────────────────
        semantic_clips = []
        if config.do_llm_clips and text_for_llm:
            logger.info("Adim 3 — LLM viral anlari tespit ediyor...")
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

        # ─── Adim 4: Stream + Kes + Analiz ───────────────────────────────
        scored_clips = []
        sliced_paths: list[str] = []

        for idx, clip in enumerate(semantic_clips):
            clip_out = str(self.temp_dir / f"stream_clip_{idx}.mp4")
            ok = await self._stream_segment_from_hls(
                hls_url, clip.get("start", 0), clip.get("end", 60), clip_out
            )
            if ok:
                sliced_paths.append(clip_out)
            else:
                logger.warning("Klip %d stream basarisiz, atlaniyor.", idx)
                sliced_paths.append("")

        if config.do_analyze:
            logger.info("Adim 4b — Unified AI analiz (stream mode)...")
            valid_paths = [(i, p) for i, p in enumerate(sliced_paths) if p]

            for orig_idx, sliced_path in valid_paths:
                clip = semantic_clips[orig_idx]
                try:
                    analysis = await ai_analyzer.analyze_clip(sliced_path)
                    scored_clips.append({
                        "idx": orig_idx, "clip": clip, "sliced_path": sliced_path,
                        "action_score": analysis.video.action_score,
                        "scene_count": analysis.video.scene_count,
                        "emotion": analysis.emotion.dominant_emotion,
                        "emotion_bonus": analysis.emotion.viral_weight,
                        "cpp_bonus": analysis.score_breakdown.get("correlation", 0),
                        "bpm": analysis.audio.bpm,
                        "loud_peaks": analysis.audio.loud_peaks,
                        "viral_moments": [m.__dict__ for m in analysis.viral_moments],
                        "viral_score": analysis.viral_score,
                        "score_breakdown": analysis.score_breakdown,
                        "reason": clip.get("reason", ""),
                    })
                except Exception as e:
                    logger.debug("Analiz hatasi (stream clip %d): %s", orig_idx, e)
                    scored_clips.append({
                        "idx": orig_idx, "clip": clip, "sliced_path": sliced_path,
                        "viral_score": 0, "reason": clip.get("reason", ""),
                    })
            scored_clips.sort(key=lambda x: x["viral_score"], reverse=True)
        elif sliced_paths:
            for idx, clip in enumerate(semantic_clips):
                if sliced_paths[idx]:
                    scored_clips.append({
                        "idx": idx, "clip": clip, "sliced_path": sliced_paths[idx],
                        "viral_score": 0, "reason": clip.get("reason", ""),
                    })

        result.scored_clips = scored_clips

        # ─── Adim 5: Render ──────────────────────────────────────────────
        final_videos: list[dict] = []
        for rank, sc in enumerate(scored_clips):
            if not sc.get("sliced_path"):
                continue

            fmt_spec = EXPORT_FORMATS.get(config.export_format, EXPORT_FORMATS["social"])
            if not config.do_render or not fmt_spec.get("use_viral_editor"):
                final_videos.append({
                    "success": True, "output_path": sc["sliced_path"],
                    "rank": rank + 1, "viral_score": sc.get("viral_score", 0),
                })
                continue

            current_input = sc["sliced_path"]
            best_res = None
            best_report = None
            round_idx = 0

            while True:
                logger.info("Adim 5 — Klip %d/%d render (tur %d)...", rank + 1, len(scored_clips), round_idx + 1)
                clip_transcript = await faster_whisper.transcribe(current_input, word_timestamps=True)
                final_res = await social_video_gen.generate_viral_video(
                    input_video_path=current_input,
                    transcript_data=clip_transcript,
                    facecam_position="auto", remove_silences=True,
                    use_brainrot=config.use_brainrot, use_bgm=config.use_bgm,
                    use_auto_zoom=config.use_auto_zoom, use_ai_denoise=config.use_ai_denoise,
                    use_auto_censor=config.use_auto_censor, inject_emojis=config.inject_emojis,
                    use_beat_sync=config.use_beat_sync, use_scene_detect=False,
                    use_effects=config.use_effects, use_stickers=config.use_stickers,
                    use_quality_check=config.use_quality_check,
                    generate_social_kit=config.do_media_kit,
                    metadata={"game": config.game, "streamer": config.streamer},
                )
                if not final_res.get("success"):
                    logger.error("Klip %d render basarisiz: %s", rank + 1, final_res.get("error"))
                    break

                if not config.use_ai_critic:
                    best_res = final_res
                    break

                report = await ai_critic.critique(
                    video_path=final_res.get("output_path", ""),
                    transcript_data=clip_transcript,
                    metadata={"game": config.game, "streamer": config.streamer},
                )
                final_res["critique"] = report.to_dict()
                logger.info("Klip %d — %s", rank + 1, report.summary().replace("\n", " "))

                if best_report is None or report.score > best_report.score:
                    best_res, best_report = final_res, report

                round_idx += 1
                if report.passed or round_idx > config.critic_max_rounds:
                    break
                any_autofix = (config.critic_autofix_hook or config.critic_autofix_subtitle
                               or config.critic_autofix_zoom or config.critic_autofix_cut)
                if not any_autofix:
                    break
                fixed_path, applied_fixes = await ai_critic.auto_fix(
                    video_path=current_input, report=report,
                    transcript_data=clip_transcript,
                    fix_round=round_idx,
                )
                if not fixed_path:
                    break
                current_input = fixed_path

            if best_res:
                best_res["rank"] = rank + 1
                best_res["viral_score"] = sc.get("viral_score", 0)
                if best_report:
                    best_res["critic_rounds"] = round_idx
                final_videos.append(best_res)

        result.success = True
        result.total_clips = len(final_videos)
        result.generated_clips = final_videos
        result.message = f"{len(final_videos)} klip uretildi (stream mode, fmt={config.export_format})"
        logger.info("=== PROCESS_STREAM TAMAMLANDI: %d klip ===", len(final_videos))
        return result.to_dict()


master_pipeline = MasterPipeline()
