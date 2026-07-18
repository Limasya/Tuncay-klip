"""
Zero-Bandwidth Clip Engine
──────────────────────────
Kick VOD'lardan clip önerileri üretirken HİÇBİR video/ses indirmez.

Mimari:
  Kick API (sadece birkaç KB JSON) → LLM metadata analizi → Clip önerileri
                                                              ↓
                                          Kullanıcı onaylarsa → Sadece o 30sn segmenti indir → Render

Bant genişliği kullanımı:
  Analiz: ~2-5 KB (API metadata JSON)
  Render: ~2-5 MB (sadece onaylanan clip segmenti, 30-60 sn)
  Toplam: 1 VOD analiz + 3 clip render ≈ 10-15 MB (vs eski: 1-3 GB tam VOD indirme)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from config import get_settings
from services.kick_api import kick_service

logger = logging.getLogger("zero_bandwidth_clipper")


@dataclass
class ClipSuggestion:
    """Tek bir clip önerisi — topluluk clip'lerinden veya LLM tahmininden."""
    clip_id: str
    title: str
    description: str
    start_time: float
    end_time: float
    duration: float
    confidence: float
    reason: str
    source: str = "llm_guess"  # "community_clip" | "llm_guess" | "hybrid"
    platform: str = "tiktok"
    thumbnail_hint: str = ""
    tags: list[str] = field(default_factory=list)
    community_views: int = 0
    community_likes: int = 0
    community_creator: str = ""


@dataclass
class VODAnalysis:
    """Bir VOD'un AI analiz sonucu."""
    vod_id: str
    vod_url: str
    title: str
    duration: float
    category: str
    created_at: str
    ai_summary: str
    highlights_detected: list[dict[str, Any]]
    clips: list[ClipSuggestion]
    analysis_time_sec: float
    bandwidth_used_kb: float
    analyzed_at: str = ""

    def __post_init__(self):
        if not self.analyzed_at:
            self.analyzed_at = datetime.now(timezone.utc).isoformat()


class ZeroBandwidthClipper:
    """Kick VOD'larını sadece metadata ile analiz edip clip önerileri üretir.

    Hiçbir video/ses indirmez. Sadece Kick API'den JSON metadata çeker
    (sadece birkaç KB) ve LLM ile analiz eder.
    """

    def __init__(self):
        self._analysis_cache: dict[str, VODAnalysis] = {}
        self._render_dir = Path("data/rendered_clips")
        self._render_dir.mkdir(parents=True, exist_ok=True)

    # ─── Adım 1: Metadata Çek (sadece birkaç KB) ───────────────────────────

    async def _fetch_vod_metadata(self, vod_url: str) -> Optional[dict[str, Any]]:
        """Kick API'den VOD metadata'sını çeker (sadece birkaç KB JSON)."""
        vod_id = self._extract_vod_id(vod_url)
        if not vod_id:
            logger.error("VOD ID çıkarılamadı: %s", vod_url)
            return None

        try:
            client = await kick_service._get_client()
            url = f"https://kick.com/api/v2/channels/thetuncay/videos"

            # curl_cffi ile Cloudflare bypass
            from curl_cffi.requests import Session as CurlSession
            def _fetch():
                session = CurlSession(impersonate="chrome124")
                resp = session.get(url, params={"limit": 20, "sort": "date"}, timeout=10)
                resp.raise_for_status()
                return resp.json()

            data = await asyncio.to_thread(_fetch)
            videos = data if isinstance(data, list) else data.get("data", [])

            for v in videos:
                vod_uuid = str(v.get("id", ""))
                vod_slug = str(v.get("slug", ""))
                if vod_id in (vod_uuid, vod_slug):
                    # Kick API metadata düzeltmeleri
                    # 1. Başlık: session_title veya slug'dan çıkar
                    v["title"] = v.get("session_title") or v.get("title") or v.get("slug", "")
                    # 2. Süre: milisaniye → saniye
                    dur = v.get("duration", 0)
                    if isinstance(dur, (int, float)) and dur > 86400:
                        v["duration"] = dur / 1000.0
                    # 3. Kategori: categories[0].name
                    cats = v.get("categories")
                    if isinstance(cats, list) and cats:
                        v["category"] = cats[0].get("name", "")

                    metadata_json = json.dumps(v, ensure_ascii=False)
                    kb = len(metadata_json.encode("utf-8")) / 1024
                    logger.info("VOD metadata alındı: %.1f KB (title: %s)", kb, v.get("title", "")[:50])
                    return v

            logger.warning("VOD bulunamadı: %s (toplam %d video tarandı)", vod_id, len(videos))
            # İlk videoyu döndür (en son VOD) — normalleştirilmiş
            if videos:
                v = videos[0]
                v["title"] = v.get("session_title") or v.get("title") or v.get("slug", "")
                dur = v.get("duration", 0)
                if isinstance(dur, (int, float)) and dur > 86400:
                    v["duration"] = dur / 1000.0
                cats = v.get("categories")
                if isinstance(cats, list) and cats:
                    v["category"] = cats[0].get("name", "")
                return v
            return None
        except Exception as e:
            logger.error("Metadata çekme hatası: %s", e)
            return None

    async def _fetch_vod_metadata_simple(self, vod_url: str) -> Optional[dict[str, Any]]:
        """Tek bir VOD'un metadata'sını çeker."""
        vod_id = self._extract_vod_id(vod_url)
        if not vod_id:
            return None

        try:
            from curl_cffi.requests import Session as CurlSession
            def _fetch():
                session = CurlSession(impersonate="chrome124")
                # Kick video sayfasından metadata çek
                resp = session.get(f"https://kick.com/api/v2/video/{vod_id}", timeout=10)
                resp.raise_for_status()
                return resp.json()

            data = await asyncio.to_thread(_fetch)
            kb = len(json.dumps(data).encode("utf-8")) / 1024
            logger.info("VOD metadata alındı: %.1f KB", kb)
            return data
        except Exception as e:
            logger.warning("Tek VOD metadata çekilemedi (%s), listeden deneniyor", e)
            return await self._fetch_vod_metadata(vod_url)

    def _extract_vod_id(self, url: str) -> Optional[str]:
        """VOD URL'sinden ID'yi çıkarır."""
        try:
            parsed = urlparse(url)
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) >= 3 and parts[1] in ("videos", "video"):
                return parts[2]
            if len(parts) >= 2:
                return parts[-1]
        except Exception:
            pass
        return None

    # ─── Adım 1b: Community Clip'leri Çek (sadece birkaç KB) ───────────────

    async def _fetch_community_clips(self, vod_id: str) -> list[dict[str, Any]]:
        """Belirli bir VOD'a ait topluluk clip'lerini çeker (sadece JSON, KB mertebesinde).

        Bu clip'ler izleyicilerin gerçekten kliplediği anları gösterir —
        LLM tahminlerinden çok daha güvenilir sinyaldir.
        """
        try:
            from curl_cffi.requests import Session as CurlSession

            def _fetch():
                session = CurlSession(impersonate="chrome124")
                resp = session.get(
                    "https://kick.com/api/v2/channels/thetuncay/clips",
                    params={"limit": 50},
                    timeout=15,
                )
                resp.raise_for_status()
                return resp.json()

            data = await asyncio.to_thread(_fetch)
            items = data if isinstance(data, list) else data.get("data", data.get("clips", []))

            # VOD ID'yi hem string hem int olarak dene
            vod_clips = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                ls_id = item.get("livestream_id")
                if not ls_id:
                    continue
                # Eşleşme: string olarak karşılaştır (livestream_id her zaman string)
                ls_id_str = str(ls_id)
                if ls_id_str == str(vod_id):
                    normalized = kick_service._normalize_clip(item)
                    if normalized:
                        vod_clips.append(normalized)

            if vod_clips:
                total_kb = len(json.dumps(vod_clips).encode("utf-8")) / 1024
                logger.info("VOD %s icin %d community clip bulundu (%.1f KB)",
                            vod_id, len(vod_clips), total_kb)
            else:
                logger.info("VOD %s icin community clip bulunamadi (toplam %d clip tarandı)",
                            vod_id, len(items))

            return vod_clips

        except Exception as e:
            logger.warning("Community clip cekme hatasi: %s", e)
            return []

    def _format_clips_for_llm(self, clips: list[dict[str, Any]]) -> str:
        """Community clip'lerini LLM prompt'u icin formatla."""
        if not clips:
            return "Bu VOD icin topluluk clip'i bulunamadi."

        lines = [f"Bu VOD'da izleyicilerin klipledigi {len(clips)} an var:"]
        for i, c in enumerate(clips[:10], 1):
            title = c.get("title", "Basliksiz")
            duration = c.get("duration", 0)
            views = c.get("views", 0) or c.get("view_count", 0)
            likes = c.get("likes", 0) or c.get("likes_count", 0)
            creator = c.get("creator_username", "")
            lines.append(
                f"  {i}. \"{title}\" ({duration}sn, {views} goruntulenme, {likes} begeni, "
                f"kiran: {creator})"
            )

        lines.append("")
        lines.append("Onemli: Bu clip'ler izleyicilerin gercekten begendigi ve kaydettigi anlar.")
        lines.append("Bu clip'lerin zaman araliklarini referans alarak ek oneriler uret.")
        lines.append("Ayrica bu clip'lerin basliklarindan icerik hakkinda cikarim yap.")
        return "\n".join(lines)

    # ─── Adım 2: LLM Analiz (sıfır bant genişliği) ────────────────────────

    async def _analyze_with_llm(
        self, metadata: dict[str, Any], community_clips: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Metadata + community clips ile LLM analiz — sıfır internet (analiz aşaması)."""
        title = str(metadata.get("session_title") or metadata.get("title") or "")
        duration_raw = metadata.get("duration", 0)
        duration_sec = float(duration_raw) if duration_raw else 3600
        if duration_sec > 86400:
            duration_sec = duration_sec / 1000.0
        category = ""
        cats = metadata.get("categories") or metadata.get("category")
        if isinstance(cats, list) and cats:
            category = cats[0].get("name", "") if isinstance(cats[0], dict) else str(cats[0])
        elif isinstance(cats, str):
            category = cats

        created = metadata.get("created_at", metadata.get("published_at", ""))

        # Community clips bağlamını oluştur
        clips_context = self._format_clips_for_llm(community_clips)

        system_prompt = (
            "Sen bir Twitch/Kick clip analiz uzmanısın. "
            "Verilen VOD metadata bilgisinden VE topluluk clip'lerinden "
            "viral clip önerileri üret. "
            "Öncelikle mevcut topluluk clip'lerini referans al, "
            "sonra bunlara ek öneriler üret. "
            "JSON formatında yanıt ver."
        )

        user_prompt = f"""Bu VOD'un metadata bilgisi:
- Başlık: {title}
- Süre: {int(duration_sec)} saniye ({int(duration_sec/60)} dakika)
- Kategori: {category or 'Bilinmiyor'}
- Tarih: {created or 'Bilinmiyor'}

Topluluk Clip Verisi:
{clips_context}

Bu bilgilere dayanarak:
1. VOD'un genel özetini çıkar
2. Mevcut topluluk clip'lerini analiz et (neden popüler olmuş olabilirler?)
3. Topluluk clip'lerine ek olarak, LLM ile tahmin ettigin yeni clip onerileri uret
4. Her oneri icin:
   - source: "community_clip" (eger mevcut clip'ten turetilmisse) veya "llm_guess" (sadece LLM tahmini)
   - start_sec/end_sec: Tahmini zaman araligi (community_clip icin 0-0 birak, zaman bilinmiyor)
   - confidence: 0.0-1.0 arasi (community_clip icin 0.7-0.95 arasi, llm_guess icin 0.3-0.6 arasi)
   - reason: Neden bu an ilginç?

Yanıtı şu JSON formatında ver:
{{
  "summary": "VOD hakkında kısa özet",
  "community_clips_analysis": "Mevcut topluluk clip'lerinin analizi",
  "highlights": [
    {{
      "start_sec": 0,
      "end_sec": 0,
      "reason": "Neden bu an ilginç?",
      "confidence": 0.8,
      "emotion": "funny/exciting/hype/emotional",
      "clip_title": "Clip başlık önerisi",
      "source": "community_clip veya llm_guess"
    }}
  ]
}}"""

        try:
            from services.llm_client import _get_router, _load_config

            router = _get_router()
            if router is None:
                # Fallback: llm_client.generate kullan
                from services.llm_client import generate
                response = await generate(
                    prompt_template="title_generation",
                    language="tr",
                    context={
                        "streamer_name": "Tuncay",
                        "category": category,
                        "emotion": "funny",
                        "custom_prompt": user_prompt,
                    },
                    max_tokens=2048,
                    temperature=0.4,
                    system_prompt=system_prompt,
                )
            else:
                config = _load_config()
                providers = config.get("tuncay_klip", {}).get("providers", {})
                model_names = [n for n, v in providers.items() if v.get("enabled")]

                response = ""
                for model_name in model_names:
                    try:
                        resp = await router.acompletion(
                            model=model_name,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            max_tokens=2048,
                            temperature=0.4,
                        )
                        content = resp.choices[0].message.content or ""
                        if len(content.strip()) > 20:
                            response = content
                            logger.info("LLM yanıt (%s): %d karakter", model_name, len(response))
                            break
                        logger.warning("LiteLLM boş yanıt (%s)", model_name)
                    except Exception as e:
                        logger.warning("LiteLLM %s hatası: %s", model_name, e)

                if not response:
                    raise RuntimeError("Tüm LLM provider'lar başarısız")

            # JSON çıkar
            import re
            raw = response.strip()

            # markdown code block temizle
            match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
            if match:
                raw = match.group(1).strip()

            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                # Parantez kontrolü
                result = None
                for open_c, close_c in [('{', '}'), ('[', ']')]:
                    depth = 0
                    start = -1
                    for i, ch in enumerate(raw):
                        if ch == open_c:
                            if depth == 0:
                                start = i
                            depth += 1
                        elif ch == close_c:
                            depth -= 1
                            if depth == 0 and start >= 0:
                                try:
                                    result = json.loads(raw[start:i+1])
                                    break
                                except json.JSONDecodeError:
                                    start = -1
                    if result is not None:
                        break
                if result is None:
                    result = {"summary": raw, "highlights": []}

            logger.info("LLM analiz tamamlandı: %d highlight bulundu",
                        len(result.get("highlights", [])))
            return result

        except Exception as e:
            logger.error("LLM analiz hatası: %s", e)
            return {"summary": "Analiz başarısız", "highlights": []}

    # ─── Adım 3: Clip Önerileri Oluştur ───────────────────────────────────

    def _build_clip_suggestions(
        self, vod_id: str, vod_url: str, metadata: dict[str, Any],
        llm_result: dict[str, Any], community_clips: list[dict[str, Any]]
    ) -> VODAnalysis:
        """LLM sonuçlarını + community clips ClipSuggestion listesine dönüştür."""
        title = str(metadata.get("session_title") or metadata.get("title") or "")
        duration_raw = metadata.get("duration", 0)
        duration_sec = float(duration_raw) if duration_raw else 3600
        if duration_sec > 86400:
            duration_sec = duration_sec / 1000.0
        category = ""
        cats = metadata.get("categories") or metadata.get("category")
        if isinstance(cats, list) and cats:
            category = cats[0].get("name", "") if isinstance(cats[0], dict) else str(cats[0])

        summary = llm_result.get("summary", "")
        community_analysis = llm_result.get("community_clips_analysis", "")
        highlights = llm_result.get("highlights", [])

        clips = []

        # Topluluk clip'lerini ClipSuggestion'a dönüştür
        for i, cc in enumerate(community_clips):
            clip_duration = float(cc.get("duration", 30))
            clip = ClipSuggestion(
                clip_id=f"{vod_id}_community_{i+1}",
                title=cc.get("title", f"Community Clip {i+1}"),
                description=f"Topluluk tarafindan klipletildi: {cc.get('title', '')}",
                start_time=0,  # VOD'daki kesin zaman bilinmiyor
                end_time=0,
                duration=clip_duration,
                confidence=0.85,  # Topluluk clip = gercek veri, yuksek guven
                reason=f"Bu an izleyiciler tarafindan klipletildi ({cc.get('views', 0)} goruntulenme)",
                source="community_clip",
                platform="tiktok",
                tags=["community_verified"],
                community_views=cc.get("views", 0) or cc.get("view_count", 0),
                community_likes=cc.get("likes", 0) or cc.get("likes_count", 0),
                community_creator=cc.get("creator_username", ""),
            )
            clips.append(clip)

        # LLM tahminlerini ClipSuggestion'a dönüştür
        for i, h in enumerate(highlights):
            start = float(h.get("start_sec", 0))
            end = float(h.get("end_sec", start + 30))
            clip_duration = end - start

            # Süre kontrolü
            if clip_duration < 5:
                end = start + 30
                clip_duration = 30
            if clip_duration > 120:
                end = start + 60
                clip_duration = 60

            # VOD süresini aşma
            if start >= duration_sec:
                start = max(0, duration_sec - 60)
                end = duration_sec
                clip_duration = end - start

            # Source belirleme
            source = h.get("source", "llm_guess")
            confidence = float(h.get("confidence", 0.5))

            # community_clip ise zamanı LLM'den gelen değerden al
            if source == "community_clip":
                # Community clip zamanı bilinmiyor, LLM tahminini kullan
                pass
            else:
                # LLM guess — confidence düşür (gerçek sinyal yok)
                confidence = min(confidence, 0.6)

            clip = ClipSuggestion(
                clip_id=f"{vod_id}_llm_{i+1}",
                title=h.get("clip_title", f"{title[:30]}... Clip {i+1}"),
                description=h.get("reason", ""),
                start_time=start,
                end_time=end,
                duration=clip_duration,
                confidence=confidence,
                reason=h.get("reason", ""),
                source=source,
                platform="tiktok",
                tags=[h.get("emotion", "funny"), category.lower()],
            )
            clips.append(clip)

        # Güven skoruna göre sırala (community_clip önce)
        clips.sort(key=lambda c: (c.source != "community_clip", -c.confidence))

        # Metadata + community clips boyutunu hesapla
        total_kb = len(json.dumps(metadata).encode("utf-8")) / 1024
        if community_clips:
            total_kb += len(json.dumps(community_clips).encode("utf-8")) / 1024

        analysis = VODAnalysis(
            vod_id=vod_id,
            vod_url=vod_url,
            title=title,
            duration=duration_sec,
            category=category,
            created_at=str(metadata.get("created_at", "")),
            ai_summary=summary + (f"\n\nTopluluk Analizi: {community_analysis}" if community_analysis else ""),
            highlights_detected=highlights,
            clips=clips,
            analysis_time_sec=0,
            bandwidth_used_kb=total_kb,
        )

        return analysis

    # ─── Ana Analiz Metodu ────────────────────────────────────────────────

    async def analyze_vod(self, vod_url: str) -> VODAnalysis:
        """VOD'u metadata + community clips ile analiz et — sıfır video/ses indirme.

        Toplam bant genişliği: ~5-15 KB (metadata + community clips JSON'u)
        """
        t0 = time.monotonic()

        vod_id = self._extract_vod_id(vod_url)
        if not vod_id:
            raise ValueError(f"Geçersiz VOD URL: {vod_url}")

        # Cache kontrolü
        if vod_id in self._analysis_cache:
            cached = self._analysis_cache[vod_id]
            logger.info("Cache'den döndürülüyor: %s", vod_id)
            return cached

        # Adım 1a: Metadata çek (sadece birkaç KB)
        logger.info("Adim 1a: VOD metadata cekiliyor (sıfır video indirme)...")
        metadata = await self._fetch_vod_metadata_simple(vod_url)
        if not metadata:
            raise ValueError(f"VOD metadata çekilemedi: {vod_url}")

        # Adım 1b: Community clips çek (sadece birkaç KB)
        # Numeric VOD ID'yi metadata'dan al (livestream_id eşleşmesi için)
        numeric_vod_id = str(metadata.get("id", vod_id))
        logger.info("Adim 1b: Community clip'ler cekiliyor (VOD numeric_id=%s)...", numeric_vod_id)
        community_clips = await self._fetch_community_clips(numeric_vod_id)

        # Adım 2: LLM analiz (metadata + community clips bağlamıyla)
        logger.info("Adim 2: LLM ile analiz ediliyor (%d community clip baglamiyla)...",
                     len(community_clips))
        llm_result = await self._analyze_with_llm(metadata, community_clips)

        # Adım 3: Clip önerileri oluştur
        analysis = self._build_clip_suggestions(vod_id, vod_url, metadata, llm_result, community_clips)
        analysis.analysis_time_sec = round(time.monotonic() - t0, 2)

        # Cache'le
        self._analysis_cache[vod_id] = analysis

        # Sonuç istatistikleri
        community_count = sum(1 for c in analysis.clips if c.source == "community_clip")
        llm_count = sum(1 for c in analysis.clips if c.source == "llm_guess")

        logger.info(
            "VOD analiz tamamlandi: %s | %d clip (%d community + %d llm) | %.1f KB | %.1f saniye",
            analysis.title[:40], len(analysis.clips), community_count, llm_count,
            analysis.bandwidth_used_kb, analysis.analysis_time_sec
        )

        return analysis

    # ─── On-Demand Clip Render (sadece onaylanan clip'i indir) ────────────

    async def render_clip(self, vod_url: str, clip: ClipSuggestion) -> dict[str, Any]:
        """Onaylanan bir clip'i indir ve render et.

        Sadece clip süresi kadar video segmenti indirilir (~2-5 MB per 30sn).
        Tam VOD indirilmez.
        """
        logger.info("Clip render başlatılıyor: %s (%.0f-%.0f sn)", clip.title, clip.start_time, clip.end_time)

        # HLS source URL al (sadece metadata, bandwidth minimal)
        hls_url = await self._get_hls_source(vod_url)
        if not hls_url:
            return {"success": False, "error": "HLS source URL alınamadı"}

        # Sadece bu segmenti indir ve render et
        output_path = self._render_dir / f"{clip.clip_id}.mp4"

        cmd = [
            "ffmpeg", "-y",
            "-headers", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\r\nReferer: https://kick.com/\r\n",
            "-ss", str(clip.start_time),
            "-i", hls_url,
            "-t", str(clip.duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]

        logger.info("FFmpeg ile clip segment indiriliyor ve render ediliyor (~%.1f MB)...", clip.duration * 64 / 8 / 1024)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            error_msg = stderr.decode(errors="replace")[-500:] if stderr else "FFmpeg failed"
            logger.error("Clip render başarısız: %s", error_msg[:200])
            return {"success": False, "error": error_msg[:500]}

        if not output_path.exists() or output_path.stat().st_size < 1024:
            return {"success": False, "error": "Render edilen clip çok küçük veya boş"}

        # MP4 doğrulama
        valid = await self._validate_mp4(str(output_path))
        if not valid:
            output_path.unlink(missing_ok=True)
            return {"success": False, "error": "Render edilen clip bozuk"}

        file_mb = output_path.stat().st_size / 1024 / 1024
        logger.info("Clip render tamamlandı: %s (%.1f MB)", output_path.name, file_mb)

        return {
            "success": True,
            "clip_path": str(output_path),
            "clip_id": clip.clip_id,
            "title": clip.title,
            "duration": clip.duration,
            "file_size_mb": round(file_mb, 2),
            "bandwidth_used_mb": round(file_mb, 2),
        }

    async def _get_hls_source(self, vod_url: str) -> Optional[str]:
        """Kick API'den HLS source URL'si al (minimal bandwidth)."""
        try:
            from curl_cffi.requests import Session as CurlSession

            vod_id = self._extract_vod_id(vod_url)
            if not vod_id:
                return None

            def _fetch():
                session = CurlSession(impersonate="chrome124")
                resp = session.get(
                    f"https://kick.com/api/v2/video/{vod_id}",
                    timeout=10,
                )
                resp.raise_for_status()
                return resp.json()

            data = await asyncio.to_thread(_fetch)

            # HLS source URL'yi bul
            source = data.get("source") or data.get("playback_url") or ""
            if not source:
                # Livestream info'dan dene
                livestream = data.get("livestream") or {}
                source = livestream.get("source") or ""

            if source and "m3u8" in source:
                logger.info("HLS source alındı (sadece URL, bandwidth: 0)")
                return source

            logger.warning("HLS source URL bulunamadı")
            return None
        except Exception as e:
            logger.error("HLS source çekme hatası: %s", e)
            return None

    async def _validate_mp4(self, path: str) -> bool:
        """FFprobe ile MP4 doğrulama."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration,format_name", "-of", "json", path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                return False
            info = json.loads(stdout.decode())
            duration = float(info.get("format", {}).get("duration", 0))
            return duration > 1.0
        except Exception:
            return False

    # ─── Çoklu VOD Analiz ─────────────────────────────────────────────────

    async def analyze_all_vods(self, limit: int = 10) -> list[VODAnalysis]:
        """Tüm VOD'ları analiz et — sıfır video/ses indirme."""
        try:
            vods = await kick_service.list_public_vods(limit=limit)
        except Exception as e:
            logger.error("VOD listesi çekilemedi: %s", e)
            return []

        analyses = []
        for vod in vods:
            url = vod.get("url", "")
            if not url:
                continue
            try:
                analysis = await self.analyze_vod(url)
                analyses.append(analysis)
            except Exception as e:
                logger.warning("VOD analiz başarısız (%s): %s", url[:50], e)

        return analyses

    def get_cached_analysis(self, vod_id: str) -> Optional[VODAnalysis]:
        """Önbelleğe alınmış analiz sonucunu getir."""
        return self._analysis_cache.get(vod_id)


# Singleton
zero_bandwidth_clipper = ZeroBandwidthClipper()
