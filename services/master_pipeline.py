"""
Otonom Master Pipeline v2 (Nihai AI Fabrika)
─────────────────────────────────────────────
Tek bir URL alarak tüm pipeline'ı çalıştırır:
yt-dlp → Faster-Whisper → Llama-3 (Semantic Clip) →
YOLOv8 (Action Score) → SceneDetect → BeatSync →
Mega Viral Editor → Thumbnail → SocialMediaAI Kit →
QC Raporu → Kullanıcıya teslim.
"""
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List

from services.youtube_downloader import youtube_downloader
from services.faster_whisper_service import faster_whisper
from services.llm_reasoner import llm_reasoner
from services.social_video_generator import social_video_gen
from services.action_recognizer import action_recognizer
from services.thumbnail_generator import thumbnail_generator
from services.scene_detection import SceneDetectionEngine
from services.social_media_ai import social_media_ai
from services.emotion_detector import emotion_detector
from services.effects_engine import effects_engine
from services.kick_archive import TARGET_CHANNEL_URL, is_target_vod_url

logger = logging.getLogger("master_pipeline")
_scene_detect = SceneDetectionEngine()


class MasterPipeline:
    def __init__(self):
        self.temp_dir = Path("data/temp_clips")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def _slice_video(self, input_video: str, start: float, end: float, index: int) -> str:
        """Uzun yayından belirtilen kesimi FFmpeg ile kopyalayıp ayırır."""
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

    async def process_url(
        self,
        url: str,
        max_clips: int = 5,
        use_brainrot: bool = True,
        use_bgm: bool = True,
        game: str = "Oyun",
        streamer: str = "Yayıncı",
    ) -> Dict[str, Any]:
        """
        ─── Master Pipeline Ana Fonksiyonu ───
        1. İndir (yt-dlp)
        2. Transkrip (Faster-Whisper)
        3. Semantic Clipping (Llama-3)
        4. YOLO Action Score + SceneDetect (Clip ranking)
        5. Her klip → Mega Viral Editor (v2)
        6. Thumbnail (Pillow)
        7. Viral Media Kit (SocialMediaAI)
        8. Sıralama ve rapor
        """
        if not is_target_vod_url(url):
            return {
                "success": False,
                "error": (
                    "This pipeline only processes public VOD URLs from "
                    f"{TARGET_CHANNEL_URL}/videos/..."
                ),
            }

        logger.info("=== MASTER PIPELINE v2 BAŞLATILDI: %s ===", url)

        # ─── Adım 1: yt-dlp ile indir ──────────────────────────────────────
        logger.info("Adım 1/7 — yt-dlp ile VOD indiriliyor...")
        dl_res = await youtube_downloader.download_video(url)
        if not dl_res.get("success"):
            return {"error": f"İndirme başarısız: {dl_res.get('error')}"}

        vod_path = dl_res["file_path"]
        vod_duration = dl_res.get("duration", 3600)
        logger.info("VOD indirildi: %s (%.0f sn)", dl_res.get("title"), vod_duration)

        # ─── Adım 2: Faster-Whisper Transkripsiyon ─────────────────────────
        logger.info("Adım 2/7 — Faster-Whisper ile transkripsiyon yapılıyor...")
        transcript = await faster_whisper.transcribe(vod_path, word_timestamps=True)
        if not transcript.get("success"):
            return {"error": "Transkripsiyon başarısız."}

        words = transcript.get("data", {}).get("words", [])
        # Zaman damgalı metin (LLM için)
        text_for_llm = " ".join(f"[{w['start']:.1f}] {w['word']}" for w in words)

        # ─── Adım 3: Llama-3 Semantic Highlight Tespiti ────────────────────
        logger.info("Adım 3/7 — Llama-3 videoyu anlıyor ve 'Elmas Klip' arıyor...")
        semantic_clips = await llm_reasoner.get_semantic_highlights(text_for_llm)

        if not semantic_clips:
            logger.warning("LLM hiç klip bulamadı — Fallback: her 60 sn'de bir klip al.")
            semantic_clips = [
                {"start": i * 60.0, "end": min((i + 1) * 60.0, vod_duration)}
                for i in range(min(max_clips, int(vod_duration // 60)))
            ]

        # Max klip sınırı
        semantic_clips = semantic_clips[:max_clips]
        logger.info("LLM %d adet potansiyel viral an buldu.", len(semantic_clips))

        # ─── Adım 4: Klipleri kes + YOLO + SceneDetect (paralel) ──────────
        logger.info("Adım 4/7 — Klipler kesiliyor ve analiz ediliyor (YOLOv8 + SceneDetect)...")

        sliced_paths: list[str] = []
        for idx, clip in enumerate(semantic_clips):
            p = await self._slice_video(vod_path, clip.get("start", 0), clip.get("end", 60), idx)
            sliced_paths.append(p)

        # Paralel YOLO + Scene + DeepFace Emotion analizi
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

        # Klipleri skora göre sırala
        # Viral Skor = YOLO aksiyon × 10 + Sahne sayısı × 0.5 + Emotion ağırlığı × 5
        scored_clips = []
        for idx, ((yolo_res, scene_res, emotion_res), clip, sliced_path) in enumerate(
            zip(analysis_results, semantic_clips, sliced_paths)
        ):
            action_score = yolo_res.get("avg_objects_per_frame", 0) if isinstance(yolo_res, dict) else 0
            scene_count = scene_res.total_scenes if hasattr(scene_res, "total_scenes") else 0

            # Emotion skoru: en güçlü viral_weight değerini al
            emotion_bonus = 0.0
            emotion_label = "neutral"
            if isinstance(emotion_res, dict) and emotion_res.get("success"):
                spikes = emotion_res.get("viral_spikes", [])
                if spikes:
                    emotion_bonus = max(s["viral_weight"] for s in spikes)
                    emotion_label = spikes[0]["emotion"]

            viral_score = round(
                action_score * 10
                + scene_count * 0.5
                + emotion_bonus * 5,
                2
            )
            scored_clips.append({
                "idx": idx,
                "clip": clip,
                "sliced_path": sliced_path,
                "action_score": action_score,
                "scene_count": scene_count,
                "emotion": emotion_label,
                "emotion_bonus": emotion_bonus,
                "viral_score": viral_score,
                "reason": clip.get("reason", ""),
            })

        # En yüksek puanlı klipleri öne al
        scored_clips.sort(key=lambda x: x["viral_score"], reverse=True)
        logger.info(
            "Klip sıralaması tamamlandı. En viral: klip #%d (skor: %.2f)",
            scored_clips[0]["idx"] if scored_clips else 0,
            scored_clips[0]["viral_score"] if scored_clips else 0,
        )

        # ─── Adım 5-7: Her klip için Mega Viral Editor + Thumbnail + SocialKit ─
        final_videos: list[dict] = []

        for rank, sc in enumerate(scored_clips):
            idx = sc["idx"]
            sliced_path = sc["sliced_path"]
            clip = sc["clip"]
            logger.info(
                "Adım 5/7 — Klip %d/%d işleniyor (Viral Skor: %.2f)...",
                rank + 1, len(scored_clips), sc["viral_score"]
            )

            # Klip transkripti
            clip_transcript = await faster_whisper.transcribe(sliced_path, word_timestamps=True)
            clip_transcript_data = clip_transcript.get("data")

            # Mega Viral Editor (tüm mekanikler)
            final_res = await social_video_gen.generate_viral_video(
                input_video_path=sliced_path,
                transcript_data=clip_transcript_data,
                facecam_position="auto",
                remove_silences=True,
                use_brainrot=use_brainrot,
                use_bgm=use_bgm,
                use_auto_zoom=True,
                use_ai_denoise=True,
                use_auto_censor=True,
                inject_emojis=True,
                use_beat_sync=True,
                use_scene_detect=False,   # Zaten yukarıda yapıldı
                use_effects=True,
                use_stickers=True,
                use_quality_check=True,
                generate_social_kit=True,
                metadata={"game": game, "streamer": streamer},
            )

            if not final_res.get("success"):
                logger.error("Klip %d render başarısız: %s", idx, final_res.get("error"))
                continue

            # ─── Adım 6: Thumbnail üret ────────────────────────────────────
            social_kit = final_res.get("social_kit") or {}
            hook_title = (
                social_kit.get("hooks", [""])[0]
                if isinstance(social_kit.get("hooks"), list)
                else "VİRAL AN"
            )
            mid_time = (clip.get("end", 60) - clip.get("start", 0)) / 2
            thumb_path = await thumbnail_generator.generate_thumbnail(
                video_path=final_res["output_path"],
                title=hook_title,
                timestamp=mid_time,
            )

            # ─── Adım 7: Medya Kiti TXT dosyası ───────────────────────────
            txt_path = str(final_res["output_path"]).replace(".mp4", "_MEDYAKIT.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"🎬 VİRAL KLİP #{rank + 1}\n")
                f.write(f"Viral Skor: {sc['viral_score']:.2f}\n")
                f.write(f"LLM Notu: {sc['reason']}\n")
                f.write(f"Baskın Duygu: {sc.get('emotion','neutral')} (Bonus: {sc.get('emotion_bonus',0):.1f})\n\n")
                if social_kit.get("success"):
                    f.write("== TİKTOK / SHORTS BAŞLIKLAR ==\n")
                    for h in social_kit.get("hooks", []):
                        f.write(f"  ▶ {h}\n")
                    f.write(f"\nAÇIKLAMA:\n{social_kit.get('description', '')}\n")
                    f.write(f"\nHASHTAGLER:\n{' '.join(social_kit.get('hashtags', []))}\n")
                f.write(f"\nKAPAK: {thumb_path}\n")
                if final_res.get("qc"):
                    f.write(f"\nQC: {final_res['qc']['summary']}\n")

            final_res.update({
                "rank": rank + 1,
                "viral_score": sc["viral_score"],
                "action_score": sc["action_score"],
                "scene_count": sc["scene_count"],
                "emotion": sc.get("emotion", "neutral"),
                "emotion_bonus": sc.get("emotion_bonus", 0.0),
                "thumbnail_path": thumb_path,
                "media_kit_path": txt_path,
            })
            final_videos.append(final_res)
            logger.info("✅ Klip %d tamamlandı: %s", rank + 1, final_res["output_path"])

        logger.info("=== MASTER PIPELINE TAMAMLANDI: %d klip üretildi ===", len(final_videos))
        return {
            "success": True,
            "message": f"{len(final_videos)} viral klip üretildi.",
            "source_vod": dl_res.get("title"),
            "total_clips": len(final_videos),
            "generated_clips": final_videos,
        }


# Singleton
master_pipeline = MasterPipeline()
