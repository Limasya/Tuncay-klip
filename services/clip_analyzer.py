"""
Clip Analiz Servisi — LLM Destekli Kancalama Tespiti
─────────────────────────────────────────────────────
- LLM ile clip analizi: hook noktaları, viral potansiyel, düzenleme önerileri
- Kancalama (hook)时间 damgası tespiti
- Edit önerileri: altyazı, kırpma, watermark, efekt, intro/outro
- JSON çıktı: {hook_timestamps, suggested_edits, description, score}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("clip_analyzer")


class ClipAnalyzer:
    """
    LLM ile clip analiz servisi.
    Clip metadata + title → detaylı analiz + hook tespiti + edit önerileri.
    """

    def __init__(self):
        self._llm_available: bool | None = None

    def _is_llm_available(self) -> bool:
        if self._llm_available is not None:
            return self._llm_available
        try:
            from services.llm_engine import llm_engine
            self._llm_available = len(llm_engine._providers) > 0
        except Exception:
            self._llm_available = False
        return self._llm_available

    async def analyze_clip(self, clip: dict[str, Any]) -> dict[str, Any]:
        """
        Tek bir klibi LLM ile analiz et.
        Returns: {
            hook_timestamps: [{t: float, reason: str, strength: int}],
            suggested_edits: [{type: str, description: str, timestamp: float|null}],
            hook_suggestion: str,  // "bu klibe nasıl kancalama ekleriz"
            description: str,
            viral_potential: int,
            edit_priority: str,  // high/medium/low
            intro_suggestion: str,
            outro_suggestion: str,
            thumbnail_suggestion: str,
        }
        """
        clip = dict(clip)
        media_context = await self._collect_media_context(clip)
        clip.update(media_context)

        if not self._is_llm_available():
            result = self._math_analyze(clip)
            result["media_context"] = media_context
            return result

        result = await self._llm_analyze(clip)
        result["media_context"] = media_context
        return result

    async def _collect_media_context(self, clip: dict[str, Any]) -> dict[str, Any]:
        """Collect real media signals when the clip has already been downloaded."""
        clip_id = str(clip.get("clip_id", ""))
        candidates = [clip.get("local_path"), clip.get("file_path")]
        if clip_id:
            candidates.append(Path("data/edited_clips") / f"raw_{clip_id}.mp4")
        media_path = next((Path(p) for p in candidates if p and Path(p).is_file()), None)

        context: dict[str, Any] = {
            "media_analyzed": False,
            "ocr_text": clip.get("ocr_text", ""),
            "voice_activity": clip.get("voice_activity", []),
        }
        if media_path is None:
            return context

        context["media_analyzed"] = True
        context["media_path"] = os.fspath(media_path)
        try:
            from services.audio_analyzer import audio_analyzer

            peaks_result, vad_result, ocr_text = await asyncio.gather(
                audio_analyzer.get_loud_peaks(os.fspath(media_path)),
                audio_analyzer.get_voice_activity(os.fspath(media_path)),
                asyncio.to_thread(self._extract_ocr_text, os.fspath(media_path)),
            )
            context["voice_activity"] = vad_result.get("segments", [])[:30]
            context["voice_activity_ratio"] = vad_result.get("speech_ratio", 0.0)
            context["loud_peaks"] = peaks_result.get("peaks", [])[:20]
            context["ocr_text"] = ocr_text or context["ocr_text"]
        except Exception as exc:
            logger.debug("Media context analysis skipped: %s", exc)

        return context

    @staticmethod
    def _extract_ocr_text(video_path: str, max_frames: int = 6) -> str:
        """Sample frames and invoke Tesseract when it is installed."""
        tesseract = shutil.which("tesseract")
        if not tesseract:
            return ""
        try:
            import cv2

            cap = cv2.VideoCapture(video_path)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if not cap.isOpened() or frame_count <= 0:
                cap.release()
                return ""

            texts: list[str] = []
            with tempfile.TemporaryDirectory(prefix="clip_ocr_") as temp_dir:
                for index in range(max_frames):
                    frame_pos = int(frame_count * (index + 1) / (max_frames + 1))
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
                    ok, frame = cap.read()
                    if not ok:
                        continue
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    image_path = Path(temp_dir) / f"frame_{index}.png"
                    cv2.imwrite(os.fspath(image_path), gray)
                    language = os.environ.get("OCR_LANG", "tur+eng")
                    result = subprocess.run(
                        [tesseract, os.fspath(image_path), "stdout", "-l", language, "--psm", "11"],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    if result.returncode == 0:
                        text = " ".join(result.stdout.split())
                        if len(text) >= 3 and text not in texts:
                            texts.append(text)
            cap.release()
            return " | ".join(texts)[:1500]
        except Exception as exc:
            logger.debug("OCR extraction skipped: %s", exc)
            return ""

    async def analyze_batch(self, clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Toplu analiz — max 5'erli gruplar."""
        if not clips:
            return []

        results = []
        batch_size = 5

        for i in range(0, len(clips), batch_size):
            batch = clips[i:i + batch_size]
            try:
                batch_results = await self._llm_analyze_batch(batch)
                results.extend(batch_results)
            except Exception as e:
                logger.warning("Batch analysis failed: %s", e)
                for c in batch:
                    results.append(self._math_analyze(c))

        return results

    # ── LLM Analysis ─────────────────────────────────────────────

    async def _llm_analyze(self, clip: dict[str, Any]) -> dict[str, Any]:
        """LLM ile tek klip analizi."""
        from services.llm_engine import llm_engine

        title = clip.get("title", "Adsız klip")
        views = clip.get("views", 0)
        likes = clip.get("likes", 0)
        duration = clip.get("duration", 0)
        creator = clip.get("creator_username", "")
        score = clip.get("score", 0)
        hook_score = clip.get("hook_score", 0)

        ocr_text = clip.get("ocr_text") or "OCR verisi bulunamadi. Metin uydurma."
        voice_activity = clip.get("voice_activity") or []
        loud_peaks = clip.get("loud_peaks") or []

        prompt = f"""Bu Kick/Twitch clip'ini TikTok, Instagram Reels, YouTube Shorts ve X için analiz et (2026 araştırması).

═══ 2026 PLATFORM ALGORİTMALARI ═══

PLATFORM SİNYAL SIRALAMASI:
- TikTok: İzleme tamamlama > DM paylaşımı > Beğeni. "Raw & Fast" estetik kazanır. Trend sesleri önemli. 21-34sn sweet spot.
- Instagram Reels: DM paylaşımı (3-5x ağırlıklı) > Kaydet > Yorum > Tamamlama. "Aesthetic & Curated". 15-30sn sweet spot. TikTok watermark'ı cezalandırılır!
- YouTube Shorts: İzleme süresi + Tıklama oranı. "Utility & Search". 15-60sn. Orijinal ses tercih edilir.
- X/Twitter: Konuşma başlatıcı. 2:20 max. 16:9 veya 1:1 çalışır.

═══ 7 HOOK FORMATI (etkinliğe göre sıralı) ═══
1. Instant-promise: 2 saniyede net değer ("Bu tüy sizi yendirecek")
2. Contradiction: Beklentileri challenge et ("Ders çalışmayı bırakın — kariyerinizi mahvediyor")
3. Before-and-after: Hızlı görsel dönüşüm (3s öncesi, 3s sonrası)
4. List-with-twist: Çoklu ipucu + sürpriz final
5. Visual confession: Ham, samimi, kırılgan ton
6. Price tag: Spesifik sayı hook'u ("30 günde 0₺'den 10K₺'ye")
7. Pattern interrupt: Beklenmedik sahne/ses değişimi

═══ DM SHARE TRIGGER'LARI (Reels 2026'nın en güçlü sinyali) ═══
- "Buna ihtiyacı olan birini etiketle"
- "Arkadaşınıza gönderin ki..."
- Relatable anlar (insanların birini düşünmesine sebep olur)
- Son 5 saniye = paylaşım için tasarlanmalı (beğeni için değil)

═══ EDİT KURALLARI ═══
- Her 2-3 saniyede sahne değişimi
- Her 3-5 saniyede zoom/jump-cut
- ASLA intro/outro yok (tamamlama oranını öldürür)
- %85 sessiz izler → animasyonlu altyazı zorunlu
- İma edilen CTA, doğrudan CTA'dan 2x daha etkili (oralama atma)

═══ SAFE ZONES (platform-specific) ═══
- TikTok: üst %15, alt %35 UI için ayrılmış
- Reels: üst %12, alt %30 UI için ayrılmış
- Shorts: üst %10, alt %25 UI için ayrılmış
- Caption safe zone: orta %60 (platform-agnostic)
- Caption: TikTok 50-75 karakter, Reels 125 karakter

BAŞLIK: {title}
İZLENME: {views}
BEĞENİ: {likes}
SÜRE: {duration}s
CREATOR: {creator}
SKOR: {score}
KANCALAMA SKORU: {hook_score}
Ekranda Tespit Edilen Yazılar (OCR): {ocr_text}
Ses Aktivitesi (VAD): {voice_activity}
Yüksek Ses / Tepki Zirveleri: {loud_peaks}

Bu klibi analiz et ve ŞU JSON formatında cevap ver (sadece JSON, başka bir şey yazma):
{{
  "hook_timestamps": [
    {{"t": 2.0, "reason": "İlk 3 saniyedeki hook tetikleyicisi", "strength": 85, "hook_type": "pattern_interrupt"}},
    {{"t": 12.0, "reason": "İkinci güçlü an", "strength": 70, "hook_type": "emotion_trigger"}}
  ],
  "hook_format": "bu klibin kullandığı/vermesi gereken hook formatı (instant_promise/contradiction/before_after/list_with_twist/visual_confession/price_tag/pattern_interrupt)",
  "hook_suggestion": "İlk 1-3 saniye için tam olarak gösterilecek Türkçe metin (merak uyandırıcı, 7 hook formatından en uygun olanına göre)",
  "send_trigger": "Son 5 saniyede DM paylaşımını artıracak tam metin/aksiyon",
  "suggested_edits": [
    {{"type": "9_16_crop", "description": "9:16 dikey kırpma — ana karakter merkezde", "platform": "both"}},
    {{"type": "hook_text_overlay", "description": "İlk 1-3sn'e dikkat çekici Türkçe metin bindirme", "platform": "both"}},
    {{"type": "animated_captions", "description": "Word-by-word karaoke altyazı — kalın, beyaz, siyah gölge, orta safe zone", "platform": "both"}},
    {{"type": "safe_zone_tiktok", "description": "TikTok: üst %15 + alt %35 temiz", "platform": "tiktok"}},
    {{"type": "safe_zone_reels", "description": "Reels: üst %12 + alt %30 temiz", "platform": "reels"}},
    {{"type": "trim_to_hook", "description": "Intro yoksa direkt hook'tan başlat", "platform": "both"}},
    {{"type": "remove_intro", "description": "Giriş bekleme kısmını kes", "platform": "both"}},
    {{"type": "remove_outro", "description": "Veda/CTA çıkışı varsa kes", "platform": "both"}},
    {{"type": "add_stock_hook", "description": "Başına stok video hook ekle", "platform": "tiktok"}},
    {{"type": "scene_change_every_3s", "description": "Her 2-3s'de jump-cut veya sahne değişimi", "platform": "both"}},
    {{"type": "zoom_on_reaction", "description": "Tepki anına slow zoom uygula", "platform": "reels"}},
    {{"type": "speed_ramp", "description": "Kritik ana 1.5x hızlanma efekti", "platform": "both"}},
    {{"type": "dm_share_overlay", "description": "Son 5s'de 'arkadaşına gönder' metni bindirme", "platform": "reels"}}
  ],
  "caption_tiktok": "TikTok caption (50-75 karakter, keyword zengin, 3-5 hashtag)",
  "caption_reels": "Instagram Reels caption (125 karakter max, konuşma başlatıcı, 3-5 hashtag)",
  "caption_shorts": "YouTube Shorts caption (araştırma-odaklı, SEO için uzun başlık)",
  "hashtags": ["#gaming", "#twitch", "#clip"],
  "emotional_trigger": "Bu klip tetiklediği birincil duygu (ör: heyecan, şaşkınlık, kahkaha, gerilim)",
  "optimal_duration_tiktok": 25,
  "optimal_duration_reels": 20,
  "optimal_duration_shorts": 30,
  "viral_potential": 75,
  "dm_share_potential": 60,
  "edit_priority": "high",
  "stock_video_queries": ["fire explosion effect", "gaming reaction overlay", "epic win celebration"],
  "description": "Klibin kısa özeti (1-2 cümle)",
  "meme_overlays": [
    {{"meme_path": "data/memes/funny_face.png", "timestamp": 5.0, "duration": 3.0, "position": "bottom_right", "scale_pct": 25, "opacity": 0.85, "animation": "fade_in"}}
  ],
  "sfx_events": [
    {{"event_type": "impact", "timestamp": 3.0, "volume_db": -8.0, "mix_ratio": 0.6}},
    {{"event_type": "whoosh", "timestamp": 10.0, "volume_db": -12.0, "mix_ratio": 0.5}}
  ],
  "music_path": "data/music/default.mp3",
  "music_volume_db": -18.0,
  "meme_potential": 70,
  "sfx_potential": 65
}}"""

        try:
            result = await llm_engine.generate(
                prompt, language="tr", max_tokens=1024,
                temperature=0.3, use_cache=True,
            )

            parsed = self._parse_json(result)
            if parsed:
                parsed["analysis_method"] = "llm"
                return self._fill_defaults(parsed, clip)

        except Exception as e:
            logger.debug("LLM analysis failed: %s", e)

        return self._math_analyze(clip)

    async def _llm_analyze_batch(self, clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Toplu LLM analizi — 5'er 5'er."""
        from services.llm_engine import llm_engine

        summaries = []
        for i, c in enumerate(clips):
            summaries.append(
                f"[{i+1}] Başlık: {c.get('title','?')} | "
                f"İzlenme: {c.get('views',0)} | Beğeni: {c.get('likes',0)} | "
                f"Süre: {c.get('duration',0)}s | Skor: {c.get('score',0)}"
            )

        prompt = f"""{len(clips)} klibi analiz et:

{chr(10).join(summaries)}

Her klip için şu JSON array'ini döndür:
[
  {{
    "index": 1,
    "hook_timestamps": [{{"t": 5.0, "reason": "açıklama", "strength": 80}}],
    "hook_suggestion": "kancalama önerisi",
    "viral_potential": 75,
    "edit_priority": "high|medium|low",
    "intro_suggestion": "intro tarzı",
    "outro_suggestion": "outro tarzı",
    "thumbnail_suggestion": "thumbnail önerisi"
  }}
]

Sadece JSON array döndür."""

        try:
            result = await llm_engine.generate(
                prompt, language="tr", max_tokens=1024,
                temperature=0.3, use_cache=True,
            )

            parsed_list = self._parse_json_array(result)
            if parsed_list and len(parsed_list) == len(clips):
                results = []
                for j, (clip, llm_data) in enumerate(zip(clips, parsed_list)):
                    analysis = self._fill_defaults(llm_data, clip)
                    analysis["analysis_method"] = "llm_batch"
                    results.append(analysis)
                return results

        except Exception as e:
            logger.debug("LLM batch analysis failed: %s", e)

        return [self._math_analyze(c) for c in clips]

    # ── Math Fallback ────────────────────────────────────────────

    def _math_analyze(self, clip: dict[str, Any]) -> dict[str, Any]:
        """LLM yoksa matematiksel analiz — TikTok/Reels odaklı."""
        duration = clip.get("duration", 30)
        views = clip.get("views", 0)
        likes = clip.get("likes", 0)
        score = clip.get("score", 50)
        title = clip.get("title", "")
        category = clip.get("category", "exciting")

        hook_ts = []
        if duration > 5:
            hook_ts.append({"t": 2.0, "reason": "İlk 3 saniye — hook zorunlu, Pattern Interrupt ekle", "strength": 75, "hook_type": "pattern_interrupt"})
        if duration > 15:
            hook_ts.append({"t": duration * 0.4, "reason": "Core bölge — zirve duygu/skill anı", "strength": 65, "hook_type": "emotion_trigger"})
        if duration > 30:
            hook_ts.append({"t": duration - 5, "reason": "Payoff — güçlü kapanış, DM share trigger'ı burada", "strength": 60, "hook_type": "curiosity_gap"})

        engagement = (likes / max(views, 1)) * 100

        opt_tiktok = max(21, min(34, duration))
        opt_reels = max(15, min(30, duration))
        opt_shorts = max(15, min(60, duration))

        title_safe = title.encode("ascii", "replace").decode()[:40] if title else "Bu klip"

        return self._fill_defaults({
            "hook_timestamps": hook_ts,
            "hook_format": "pattern_interrupt" if score > 60 else "instant_promise",
            "send_trigger": f"Bunu görmesi gereken arkadaşına gönder!" if category in ("funny", "exciting") else f"Send this to someone who needs to see it",
            "suggested_edits": [
                {"type": "9_16_crop", "description": "9:16 dikey kırpma — 1080x1920, safe zone ayarla", "platform": "both"},
                {"type": "animated_captions", "description": "Word-by-word karaoke altyazı — kalın, kontrastlı, orta safe zone", "platform": "both"},
                {"type": "remove_intro", "description": "Intro varsa kes — direkt hook'tan başla", "platform": "both"},
                {"type": "remove_outro", "description": "Outro varsa kes — payoff'ta bitir", "platform": "both"},
                {"type": "hook_text_overlay", "description": "İlk 1-3sn'e merak uyandıran büyük Türkçe metin bindirme", "platform": "both"},
                {"type": "safe_zone_tiktok", "description": "TikTok: üst %15 + alt %35 temiz tut", "platform": "tiktok"},
                {"type": "safe_zone_reels", "description": "Reels: üst %12 + alt %30 temiz tut", "platform": "reels"},
                {"type": "dm_share_overlay", "description": "Son 5s'de 'arkadaşına gönder' bindirme (Reels #1 sinyal)", "platform": "reels"},
                {"type": "scene_change_every_3s", "description": "Her 2-3s'de jump-cut ile sahne değişimi", "platform": "both"},
            ],
            "hook_suggestion": f"İlk 3sn'de şu metni göster: 'Bu clip her şeyi değiştiriyor...' "
                f"{'Güçlü giriş — hook çoktan var!' if engagement > 5 else 'Giriş güçlendirilmeli — contradiction veya pattern interrupt dene.'}",
            "caption_tiktok": f"Bu clip'i kaçırmayın! {title_safe} #gaming #twitch #clip #viral #fyp",
            "caption_reels": f"Bu neydi così?? Düşüncelerinizi yorumlara yazın! #gaming #reels #clip #viral",
            "caption_shorts": f"{title_safe} — Detaylı analiz ve en iyi anlar",
            "hashtags": ["#gaming", "#twitch", "#clip", "#viral", "#fyp"],
            "emotional_trigger": "heyecan" if score > 70 else "merak" if score > 50 else "eğlence",
            "optimal_duration_tiktok": opt_tiktok,
            "optimal_duration_reels": opt_reels,
            "optimal_duration_shorts": opt_shorts,
            "viral_potential": min(100, int(engagement * 5 + score * 0.3)),
            "dm_share_potential": 50 + (10 if category in ("funny", "wholesome") else 5),
            "edit_priority": "high" if score > 70 else "medium" if score > 50 else "low",
            "stock_video_queries": [
                "gaming highlight effect",
                "fire explosion overlay",
                "victory celebration effect",
            ],
            "meme_overlays": self._suggest_memes_for_math(clip),
            "sfx_events": self._suggest_sfx_for_math(clip),
            "music_path": "data/music/default.mp3",
            "music_volume_db": -18.0,
            "meme_potential": min(100, int(score * 0.8 + (15 if category in ("funny", "exciting") else 5))),
            "sfx_potential": min(100, int(score * 0.7 + (10 if category in ("exciting", "dramatic") else 0))),
            "description": f"{duration}s süren klip — {format_number(views)} izlenme",
            "analysis_method": "math",
        }, clip)

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _suggest_memes_for_math(clip: dict) -> list[dict]:
        """LLM yoksa matematiksel meme önerileri üret."""
        import os
        from pathlib import Path

        memes_dir = Path("data/memes")
        available = []
        if memes_dir.exists():
            for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                for f in memes_dir.rglob(ext):
                    available.append(str(f))

        if not available:
            return []

        duration = clip.get("duration", 30)
        score = clip.get("score", 50)
        category = clip.get("category", "exciting")
        overlays = []

        if score > 65:
            from random import choice
            hook_ts = clip.get("hook_timestamps", [{}])
            hook_time = hook_ts[0].get("t", 2.0) if hook_ts else 2.0

            overlays.append({
                "meme_path": choice(available),
                "timestamp": min(hook_time + 0.5, duration - 5),
                "duration": 2.5,
                "position": "bottom_right",
                "scale_pct": 25,
                "opacity": 0.85,
                "animation": "fade_in",
            })

            if score > 80 and duration > 20:
                overlays.append({
                    "meme_path": choice(available),
                    "timestamp": duration * 0.6,
                    "duration": 2.0,
                    "position": "top_left",
                    "scale_pct": 20,
                    "opacity": 0.80,
                    "animation": "scale_pop",
                })

        return overlays

    @staticmethod
    def _suggest_sfx_for_math(clip: dict) -> list[dict]:
        """LLM yoksa matematiksel SFX önerileri üret."""
        duration = clip.get("duration", 30)
        score = clip.get("score", 50)
        category = clip.get("category", "exciting")
        events = []

        hook_ts = clip.get("hook_timestamps", [])
        for h in hook_ts[:2]:
            events.append({
                "event_type": "impact",
                "timestamp": h.get("t", 2.0),
                "volume_db": -8.0,
                "mix_ratio": 0.6,
            })

        if category in ("funny", "exciting") and duration > 10:
            events.append({
                "event_type": "record_scratch",
                "timestamp": max(5.0, duration * 0.4),
                "volume_db": -10.0,
                "mix_ratio": 0.5,
            })

        if not events and score > 50:
            events.append({
                "event_type": "impact",
                "timestamp": 2.0,
                "volume_db": -10.0,
                "mix_ratio": 0.5,
            })

        return events

    @staticmethod
    def _fill_defaults(analysis: dict, clip: dict) -> dict:
        """Eksik alanları doldur — TikTok/Reels/Shorts/X alanları dahil."""
        analysis.setdefault("hook_timestamps", [])
        analysis.setdefault("hook_format", "pattern_interrupt")
        analysis.setdefault("hook_suggestion", "")
        analysis.setdefault("send_trigger", "")
        analysis.setdefault("suggested_edits", [])
        analysis.setdefault("description", "")
        analysis.setdefault("viral_potential", 50)
        analysis.setdefault("dm_share_potential", 50)
        analysis.setdefault("edit_priority", "medium")
        analysis.setdefault("caption_tiktok", "")
        analysis.setdefault("caption_reels", "")
        analysis.setdefault("caption_shorts", "")
        analysis.setdefault("hashtags", ["#gaming", "#twitch", "#clip"])
        analysis.setdefault("emotional_trigger", "heyecan")
        analysis.setdefault("optimal_duration_tiktok", 25)
        analysis.setdefault("optimal_duration_reels", 20)
        analysis.setdefault("optimal_duration_shorts", 30)
        analysis.setdefault("stock_video_queries", [])
        analysis.setdefault("meme_overlays", [])
        analysis.setdefault("sfx_events", [])
        analysis.setdefault("music_path", "")
        analysis.setdefault("music_volume_db", -18.0)
        analysis.setdefault("meme_potential", 50)
        analysis.setdefault("sfx_potential", 50)
        analysis.setdefault("analysis_method", "unknown")
        return analysis

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """LLM yanıtından JSON parse et."""
        if not text:
            return None
        import re
        cleaned = text.strip()
        cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"```\s*$", "", cleaned)

        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            raw = cleaned[start:end]
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
            fixed = raw.replace(",\n}", "\n}").replace(",}", "}")
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _parse_json_array(text: str) -> Optional[list]:
        """LLM yanıtından JSON array parse et."""
        if not text:
            return None
        import re
        cleaned = text.strip()
        cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"```\s*$", "", cleaned)

        start = cleaned.find("[")
        end = cleaned.rfind("]") + 1
        if start >= 0 and end > start:
            raw = cleaned[start:end]
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
            fixed = raw.replace(",\n]", "\n]").replace(",]", "]")
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass
        return None


def format_number(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


# Singleton
clip_analyzer = ClipAnalyzer()
