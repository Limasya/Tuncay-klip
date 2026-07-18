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

────────────────────────────────────────────────────────────────────────────────
TOPLULUK CLIP POLITIKASI (HAK/TİFLİF)
────────────────────────────────────────────────────────────────────────────────
Community clip'ler SADECE zaman/ilgi sinyali olarak kullanılır.

Nasıl çalışır:
  1. Kick API'den topluluk clip metadata'sı çekilir (sadece JSON, video indirilmez)
  2. Bu clip'ler "bu VOD'un bu bölümü ilgi çekici" sinyali olarak LLM'e bağlam verir
  3. LLM bu sinyalleri ve VOD metadata'sını analiz ederek clip önerileri üretir
  4. Nihai render her zaman ana VOD kaynağından (HLS stream) kendi pipeline'ımızla yapılır

Neden bu şekilde:
  - İzleyicinin oluşturduğu klip dosyası (m3u8/mp4) doğrudan yayınlanmaz
  - Community clip'in içindeki video yayıncının yayını + izleyicinin editoryal seçimi
  - İzin vermeden birinin clip dosyasını kullanmak telif/hak sorunu olabilir
  - Bu tasarım: izleyicinin clip'i sinyal olarak kullanılır, ancak kendi kaynağımızdan render ederiz

NOT: render_clip() fonksiyonu her zaman vod_url'den (ana VOD HLS kaynağından) render eder,
     community clip URL'si asla doğrudan render kaynağı olarak kullanılmaz.
────────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
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
    estimated_position_sec: float = 0.0
    position_confidence: str = "none"  # "none" | "approximate" | "exact"


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

    Ses-only Fallback:
      Community clip'i olmayan VOD'lar için opsiyonel olarak ses-only
      transkripsiyon yapılabilir. Bu mod aktif edildiğinde:
      - AAC 64kbps ses indirilir (~28.8 MB/saat)
      - faster-whisper ile transkripsiyon yapılır
      - Transkripsiyon sonucu LLM'e bağlam olarak sunulur
      - Bu mod bant genişliği kullanır, bu yüzden varsayılan kapalıdır.
    """

    def __init__(self):
        self._analysis_cache: dict[str, VODAnalysis] = {}
        self._render_dir = Path("data/rendered_clips")
        self._render_dir.mkdir(parents=True, exist_ok=True)
        self.audio_only_fallback_enabled: bool = False
        # Cloudflare risk takibi
        self._cf_block_count: int = 0
        self._cf_last_block_time: float = 0
        self._cf_alert_logged: bool = False
        self._cf_last_discord_alert_time: float = 0  # spam cooldown icin

    # Cloudflare sabitleri — yeni tarayici surumleri guncellenecek
    # curl_cffi docs: https://github.com/lexiforest/curl_cffi
    # Yeni Chrome surumu ciktikca burasi guncellenmeli
    _CF_IMPERSONATE = "chrome124"

    # FFmpeg icin Kick.com header'lari — curl_cffi'nin impersonate'i gibi
    # zamanla Kick sunuculari bu User-Agent'i reddedebilir, guncel gerekebilir.
    _FFMPEG_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    _FFMPEG_REFERER = "https://kick.com/"

    def _check_cloudflare_block(self, status_code: int, response_text: str) -> bool:
        """Cloudflare tarafindan engellenip engellenmedigini kontrol et.

        Cloudflare belirtileri:
        - 403 Forbidden (CF challenge)
        - 503 Service Unavailable (CF maintenance/blocked)
        - Response icinde 'cf-' header'lari veya challenge sayfasi
        """
        if status_code in (403, 503):
            self._cf_block_count += 1
            self._cf_last_block_time = time.monotonic()

            if not self._cf_alert_logged or self._cf_block_count % 10 == 0:
                logger.critical(
                    "CLOUDFLARE ALARMI: %d kez engellendi! "
                    "Impersonate surumu: %s. "
                    "Yeni Chrome surumuna gecilmesi gerekebilir. "
                    "Son yanit (ilk 200 karakter): %s",
                    self._cf_block_count,
                    self._CF_IMPERSONATE,
                    response_text[:200],
                )
                self._cf_alert_logged = True
                self._send_cf_alert(
                    "Cloudflare Engelleme",
                    f"{self._cf_block_count} kez engellendi. "
                    f"Impersonate: {self._CF_IMPERSONATE}. "
                    f"Yeni Chrome surumuna gecilmesi gerekebilir.",
                )
            return True

        # Challenge sayfasi kontrolu (CF bazen 200 dondurur ama challenge icerir)
        if status_code == 200 and response_text:
            text_lower = response_text[:1000].lower()
            if any(marker in text_lower for marker in [
                "cf-browser-verification",
                "cloudflare",
                "challenge-platform",
                "checking your browser",
                "just a moment",
            ]):
                self._cf_block_count += 1
                self._cf_last_block_time = time.monotonic()
                logger.critical(
                    "CLOUDFLARE CHALLENGE ALGILANDI (200 ama challenge sayfasi)! "
                    "Impersonate: %s | Toplam engelleme: %d",
                    self._CF_IMPERSONATE, self._cf_block_count,
                )
                self._send_cf_alert(
                    "Cloudflare Challenge Sayfasi",
                    f"200 dondu ama challenge sayfasi algilandi. "
                    f"Impersonate: {self._CF_IMPERSONATE} | Toplam: {self._cf_block_count}",
                )
                return True

        return False

    def _send_cf_alert(self, title: str, message: str) -> None:
        """Cloudflare alarmi Discord webhook uzerinden gonder.

        Spam onleme: ayni hata tipi icin 15 dakikada sadece 1 mesaj gider.
        Bu sure dolmadan yapilan cagirilar atlanir.
        """
        import time as _time
        now = _time.monotonic()
        COOLDOWN_SEC = 900  # 15 dakika

        if (now - self._cf_last_discord_alert_time) < COOLDOWN_SEC:
            logger.debug(
                "Cloudflare Discord cooldown aktif (%.0f saniye kaldi), mesaj atlandi",
                COOLDOWN_SEC - (now - self._cf_last_discord_alert_time),
            )
            return

        try:
            from config import get_settings
            settings = get_settings()
            webhook_url = settings.discord_webhook_url

            if not webhook_url:
                logger.debug("Discord webhook URL tanimli degil, Cloudflare alarmi atlandi")
                return

            import httpx
            payload = {
                "embeds": [{
                    "title": f"!! CLOUDFLARE ALARMI: {title}",
                    "description": message,
                    "color": 0xFF0000,
                    "fields": [
                        {"name": "Impersonate", "value": self._CF_IMPERSONATE, "inline": True},
                        {"name": "Toplam Engelleme", "value": str(self._cf_block_count), "inline": True},
                    ],
                    "footer": {"text": "Zero-Bandwidth Clipper"},
                }],
            }

            # Senkron HTTP — kritik alarm, block olmali
            with httpx.Client(timeout=5) as client:
                resp = client.post(webhook_url, json=payload)
                if resp.status_code < 300:
                    logger.info("Cloudflare alarmi Discord'a gonderildi")
                    self._cf_last_discord_alert_time = now
                else:
                    logger.warning("Discord webhook hatasi: %d", resp.status_code)

        except Exception as e:
            logger.warning("Cloudflare alarmi gonderilemedi: %s", e)

    def get_cf_health(self) -> dict[str, Any]:
        """Cloudflare saglik durumu."""
        return {
            "cf_block_count": self._cf_block_count,
            "cf_last_block_time": self._cf_last_block_time,
            "impersonate_version": self._CF_IMPERSONATE,
            "is_healthy": self._cf_block_count == 0,
            "recommendation": (
                "Durum normal."
                if self._cf_block_count == 0
                else f"{self._cf_block_count} engelleme. Impersonate surumunu guncelleyin: {self._CF_IMPERSONATE}"
            ),
        }

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

    # ─── Zaman Tabanlı Clip Doğrulama ──────────────────────────────────────

    @staticmethod
    def _validate_clip_timing(
        clip: dict[str, Any], vod_start_time: str, vod_duration: float,
        tolerance_sec: float = 120,
    ) -> tuple[bool, str]:
        """Bir community clip'in created_at'i VOD zaman aralığı içinde mi kontrol et.

        Neden: livestream_id reuse olabilir — aynı ID farklı yayınları işaret edebilir.
        Zaman doğrulaması: clip.created_at ∈ [vod_start - tolerance, vod_start + duration + tolerance]

        Returns: (is_valid, reason)
        """
        clip_created = clip.get("created_at", "")
        if not clip_created or not vod_start_time or vod_duration <= 0:
            return (True, "dogrulama_yapilamadi")

        def _parse_dt(s: str):
            if not s:
                return None
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"]:
                try:
                    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
                except Exception:
                    pass
            return None

        clip_dt = _parse_dt(clip_created)
        vod_dt = _parse_dt(vod_start_time)

        if not clip_dt or not vod_dt:
            return (True, "parse_edilemedi")

        tolerance = timedelta(seconds=tolerance_sec)
        vod_end = vod_dt + timedelta(seconds=vod_duration)

        if (vod_dt - tolerance) <= clip_dt <= (vod_end + tolerance):
            return (True, "zaman_araliginda")
        else:
            diff = (clip_dt - vod_dt).total_seconds()
            diff_min = diff / 60
            if diff < 0:
                reason = f"VOD'dan {abs(diff_min):.1f} dk once"
            else:
                reason = f"VOD bitiminden {diff_min - vod_duration/60:.1f} dk sonra"
            return (False, reason)

    def _filter_clips_by_timing(
        self, clips: list[dict[str, Any]], vod_start_time: str, vod_duration: float
    ) -> list[dict[str, Any]]:
        """Clip listesinden zaman aralığı dışındakileri reddet."""
        if not clips or not vod_start_time or vod_duration <= 0:
            return clips

        valid = []
        rejected = 0
        for c in clips:
            is_valid, reason = self._validate_clip_timing(c, vod_start_time, vod_duration)
            if is_valid:
                valid.append(c)
            else:
                rejected += 1
                logger.warning(
                    "Clip reddedildi (zaman dogrulamasi): '%s' (created: %s) — %s",
                    c.get("title", ""), c.get("created_at", ""), reason,
                )

        if rejected > 0:
            logger.info(
                "Zaman dogrulamasi: %d clip gecerli, %d reddedildi (tolerans: ±120s)",
                len(valid), rejected,
            )

        return valid

    # ─── Adım 1b: Community Clip'leri Çek (sadece birkaç KB) ───────────────

    async def _fetch_community_clips(self, vod_id: str) -> list[dict[str, Any]]:
        """Belirli bir VOD'a ait topluluk clip'lerini çeker (sadece JSON, KB mertebesinde).

        Bu clip'ler izleyicilerin gerçekten kliplediği anları gösterir —
        LLM tahminlerinden çok daha güvenilir sinyaldir.
        """
        try:
            from curl_cffi.requests import Session as CurlSession

            def _fetch():
                session = CurlSession(impersonate=self._CF_IMPERSONATE)
                resp = session.get(
                    "https://kick.com/api/v2/channels/thetuncay/clips",
                    params={"limit": 50},
                    timeout=15,
                )
                return resp.status_code, resp.text

            status_code, response_text = await asyncio.to_thread(_fetch)

            # Cloudflare algilama
            if self._check_cloudflare_block(status_code, response_text):
                logger.warning("Community clip'ler Cloudflare tarafindan engellendi (HTTP %d)", status_code)
                return []

            if status_code != 200:
                logger.warning("Community clip API hatasi: HTTP %d", status_code)
                return []

            data = json.loads(response_text)
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

    def _format_clips_for_llm(self, clips: list[dict[str, Any]], vod_start_time: str = "", vod_duration: float = 0) -> str:
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

            # Yaklaşık konum bilgisi
            pos_info = ""
            if vod_start_time and vod_duration > 0:
                created = c.get("created_at", "")
                est, conf = self._estimate_clip_position(created, vod_start_time, vod_duration)
                if conf == "approximate":
                    pos_info = f", tahmini konum: ~{int(est)}s ({est/60:.1f} dk, ±90s)"

            lines.append(
                f"  {i}. \"{title}\" ({duration}sn, {views} goruntulenme, {likes} begeni, "
                f"kiran: {creator}{pos_info})"
            )

        lines.append("")
        lines.append("Onemli: Bu clip'ler izleyicilerin gercekten begendigi ve kaydettigi anlar.")
        lines.append("Tahmini konumlar clip.created_at - vod.start_time farkindan hesaplanmistir (±90s tolerans).")
        lines.append("Bu clip'lerin zaman araliklarini referans alarak ek oneriler uret.")
        lines.append("Ayrica bu clip'lerin basliklarindan icerik hakkinda cikarim yap.")
        return "\n".join(lines)

    # ─── Adım 2: LLM Analiz (sıfır bant genişliği) ────────────────────────

    async def _analyze_with_llm(
        self, metadata: dict[str, Any], community_clips: list[dict[str, Any]],
        transcription_text: Optional[str] = None,
    ) -> dict[str, Any]:
        """Metadata + community clips + (opsiyonel) ses transkripsiyonu ile LLM analiz."""
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
        vod_start = str(metadata.get("start_time") or metadata.get("created_at", ""))

        # Community clips bağlamını oluştur (tahmini konumlar dahil)
        clips_context = self._format_clips_for_llm(community_clips, vod_start, duration_sec)

        # Ses transkripsiyonu baglami ekle (fallback)
        if transcription_text:
            clips_context += (
                f"\n\nSes Transkripsiyonu (community clip olmayan VOD icin ses-only analiz):\n"
                f"{transcription_text[:3000]}"
            )

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

    @staticmethod
    def _calculate_community_confidence(
        views: int, likes: int, max_views_in_vod: int, same_area_count: int
    ) -> float:
        """Community clip confidence'ını engagement'a göre ağırlıklandır.

        Formül:
          base = 0.50 (0 view için bile bir sinyal var)
          view_bonus: max_views_in_vod'a göreceli (0.00 - 0.25)
          like_bonus: likes'a göre (0.00 - 0.10)
          cluster_bonus: aynı bölgede birden fazla clip varsa (0.00 - 0.15)
          cap: 0.95 (asla kesin değil)

        Kanal küçük olduğu için mutlak sayılar düşük kalır —
        bu yüzden kanal-göreceli normalize kullanılır.
        """
        base = 0.50

        # View bonus: bu VOD'daki en çok view alan klibe göreceli
        if max_views_in_vod > 0:
            view_ratio = min(views / max_views_in_vod, 1.0)
        else:
            view_ratio = 0.0
        view_bonus = view_ratio * 0.25

        # Like bonus: mutlak olarak (kanal küçük olduğu için)
        like_bonus = min(likes * 0.02, 0.10)

        # Cluster bonus: aynı bölgede 3+ clip = güçlü sinyal
        if same_area_count >= 5:
            cluster_bonus = 0.15
        elif same_area_count >= 3:
            cluster_bonus = 0.10
        elif same_area_count >= 2:
            cluster_bonus = 0.05
        else:
            cluster_bonus = 0.0

        confidence = min(base + view_bonus + like_bonus + cluster_bonus, 0.95)
        return round(confidence, 3)

    @staticmethod
    def _estimate_clip_position(
        clip_created_at: str, vod_start_time: str, vod_duration: float
    ) -> tuple[float, str]:
        """clip.created_at - vod.start_time farkından yaklaşık VOD-içi konum tahmini.

        Returns: (estimated_position_sec, position_confidence)
        """
        if not clip_created_at or not vod_start_time or vod_duration <= 0:
            return (0.0, "none")

        def _parse_dt(s: str):
            if not s:
                return None
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"]:
                try:
                    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
                except Exception:
                    pass
            return None

        clip_dt = _parse_dt(clip_created_at)
        vod_dt = _parse_dt(vod_start_time)

        if not clip_dt or not vod_dt:
            return (0.0, "none")

        diff_sec = (clip_dt - vod_dt).total_seconds()

        # Mantıklı aralık kontrolü: 0 ile VOD süresi arasında olmalı
        # ±120 saniye tolerans (stream başlangıç/son sapmaları için)
        if diff_sec < -120 or diff_sec > vod_duration + 120:
            return (0.0, "none")

        # VOD süresi içindeyse
        estimated = max(0.0, min(diff_sec, vod_duration))
        return (estimated, "approximate")

    @staticmethod
    def _detect_clip_clusters(
        community_clips: list[dict[str, Any]], vod_start_time: str
    ) -> dict[str, int]:
        """Community clip'lerinin zaman bazlı cluster'larını tespit et.

        Aynı 3 dakikalık pencere içine düşen clip'leri gruplar.
        Returns: {clip_index: same_area_count}
        """
        if not community_clips or not vod_start_time:
            return {}

        def _parse_dt(s: str):
            if not s:
                return None
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                return None

        vod_dt = _parse_dt(vod_start_time)
        if not vod_dt:
            return {}

        # Her clip için saniye cinsinden pozisyonu hesapla
        positions = []
        for c in community_clips:
            clip_dt = _parse_dt(c.get("created_at", ""))
            if clip_dt and vod_dt:
                pos = (clip_dt - vod_dt).total_seconds()
                positions.append(pos)
            else:
                positions.append(None)

        # Cluster tespiti: 180 saniye (3 dk) pencere
        WINDOW = 180
        clusters = {}
        for i, pos_i in enumerate(positions):
            if pos_i is None:
                clusters[i] = 0
                continue
            count = 0
            for j, pos_j in enumerate(positions):
                if i != j and pos_j is not None and abs(pos_i - pos_j) <= WINDOW:
                    count += 1
            clusters[i] = count + 1  # +1: kendisi dahil

        return clusters

    # ─── Ses-only Fallback (community clip yoksa) ──────────────────────────

    async def _transcribe_audio_only(
        self, hls_url: str, duration_sec: float
    ) -> Optional[str]:
        """Sadece ses indirip faster-whisper ile transkripsiyon yapar.

        AAC 64kbps = ~28.8 MB/saat. 2 saatlik VOD icin ~57.6 MB.
        Sadece community clip'i olmayan VOD'larda kullanilir.
        """
        try:
            import subprocess
            import tempfile

            audio_chunks_dir = Path(tempfile.mkdtemp(prefix="kb_audio_"))

            # 5 dakikalik chunk'lara bol (cok buyuk dosya olusturmayalim)
            chunk_duration = 300  # 5 dk
            total_chunks = int(duration_sec / chunk_duration) + 1
            chunk_texts = []

            for ci in range(min(total_chunks, 24)):  # max 2 saat
                start = ci * chunk_duration
                chunk_path = audio_chunks_dir / f"chunk_{ci:03d}.aac"

                cmd = [
                    "ffmpeg", "-y",
                    "-headers", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\r\nReferer: https://kick.com/\r\n",
                    "-ss", str(start),
                    "-i", hls_url,
                    "-t", str(chunk_duration),
                    "-vn",
                    "-c:a", "aac", "-b:a", "64k",
                    "-ac", "1", "-ar", "16000",
                    str(chunk_path),
                ]

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=60)

                if proc.returncode != 0 or not chunk_path.exists():
                    continue

                # faster-whisper ile transkripsiyon
                try:
                    from faster_whisper import WhisperModel
                    model = WhisperModel("tiny", device="cpu", compute_type="int8")
                    segments, _ = model.transcribe(
                        str(chunk_path), language="tr",
                        beam_size=1, vad_filter=True,
                    )
                    chunk_text = " ".join(seg.text for seg in segments)
                    if chunk_text.strip():
                        chunk_texts.append(f"[{start//60:.0f}dk] {chunk_text.strip()}")
                except Exception as e:
                    logger.warning("Chunk %d transkripsiyon hatasi: %s", ci, e)

                # Gecici dosyayi sil
                try:
                    chunk_path.unlink(missing_ok=True)
                except Exception:
                    pass

            # Gecici dizini temizle
            try:
                audio_chunks_dir.rmdir()
            except Exception:
                pass

            if chunk_texts:
                full_text = "\n".join(chunk_texts)
                logger.info("Ses-only transkripsiyon tamamlandi: %d chunk, %d karakter",
                           len(chunk_texts), len(full_text))
                return full_text

            logger.warning("Ses-only transkripsiyon: hicbir metin cikarilamadi")
            return None

        except Exception as e:
            logger.error("Ses-only transkripsiyon hatasi: %s", e)
            return None

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

        # Community clip'ler için cluster tespiti yap
        vod_start = str(metadata.get("start_time") or metadata.get("created_at", ""))
        cluster_map = self._detect_clip_clusters(community_clips, vod_start)

        # Bu VOD'daki en çok view alan clip'i bul (normalize için)
        max_views = max(
            (cc.get("views", 0) or cc.get("view_count", 0) for cc in community_clips),
            default=0,
        )

        # Topluluk clip'lerini ClipSuggestion'a dönüştür
        for i, cc in enumerate(community_clips):
            clip_duration = float(cc.get("duration", 30))
            views = cc.get("views", 0) or cc.get("view_count", 0)
            likes = cc.get("likes", 0) or cc.get("likes_count", 0)
            same_area_count = cluster_map.get(i, 1)

            # Engagement-ağırlıklı confidence
            conf = self._calculate_community_confidence(
                views=views, likes=likes,
                max_views_in_vod=max_views,
                same_area_count=same_area_count,
            )

            # Yaklaşık VOD-içi konum tahmini
            clip_created = cc.get("created_at", "")
            est_pos, pos_conf = self._estimate_clip_position(
                clip_created, vod_start, duration_sec
            )

            # Tolerans penceresi bilgisi
            reason_parts = [
                f"Bu an izleyiciler tarafindan klipletildi ({views} goruntulenme)",
            ]
            if same_area_count > 1:
                reason_parts.append(
                    f"{same_area_count} klip ayni bolgeye dustu (guvenli bolge)"
                )
            if pos_conf == "approximate":
                reason_parts.append(
                    f"Tahmini VOD konumu: ~{int(est_pos)}s ({est_pos/60:.1f} dk, ±90s tolerans)"
                )

            clip = ClipSuggestion(
                clip_id=f"{vod_id}_community_{i+1}",
                title=cc.get("title", f"Community Clip {i+1}"),
                description=f"Topluluk tarafindan klipletildi: {cc.get('title', '')}",
                start_time=0,  # VOD'daki kesin zaman bilinmiyor
                end_time=0,
                duration=clip_duration,
                confidence=conf,
                reason=" | ".join(reason_parts),
                source="community_clip",
                platform="tiktok",
                tags=["community_verified"],
                community_views=views,
                community_likes=likes,
                community_creator=cc.get("creator_username", ""),
                estimated_position_sec=est_pos,
                position_confidence=pos_conf,
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

        # Duration ve start_time hesapla (fallback icin gerekli)
        duration_raw = metadata.get("duration", 0)
        duration_sec = float(duration_raw) if duration_raw else 3600
        if duration_sec > 86400:
            duration_sec = duration_sec / 1000.0
        vod_start = str(metadata.get("start_time") or metadata.get("created_at", ""))

        # Adım 1b: Community clips çek (sadece birkaç KB)
        # Numeric VOD ID'yi metadata'dan al (livestream_id eşleşmesi için)
        numeric_vod_id = str(metadata.get("id", vod_id))
        logger.info("Adim 1b: Community clip'ler cekiliyor (VOD numeric_id=%s)...", numeric_vod_id)
        community_clips = await self._fetch_community_clips(numeric_vod_id)

        # Adım 1c: Zaman tabanlı doğrulama — livestream_id reuse kontrolü
        if community_clips and vod_start and duration_sec > 0:
            before_count = len(community_clips)
            community_clips = self._filter_clips_by_timing(
                community_clips, vod_start, duration_sec
            )
            after_count = len(community_clips)
            if before_count != after_count:
                logger.warning(
                    "Zaman dogrulamasi: %d -> %d clip (%d reddedildi, VOD: %s)",
                    before_count, after_count, before_count - after_count, vod_start,
                )

        # Ses-only fallback: community clip yoksa ve enabled ise
        transcription_text = None
        if not community_clips and self.audio_only_fallback_enabled:
            logger.info("Community clip yok, ses-only fallback baslatiliyor...")
            hls_url = await self._get_hls_source(vod_url)
            if hls_url:
                transcription_text = await self._transcribe_audio_only(hls_url, duration_sec)
                if transcription_text:
                    logger.info("Ses transkripsiyonu basarili: %d karakter", len(transcription_text))

        # Adım 2: LLM analiz (metadata + community clips + ses transkripsiyonu)
        logger.info("Adim 2: LLM ile analiz ediliyor (%d community clip, transcription=%s)...",
                     len(community_clips), "var" if transcription_text else "yok")
        llm_result = await self._analyze_with_llm(metadata, community_clips, transcription_text)

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

        Telif/Hak: Render her zaman vod_url'den (ana VOD HLS kaynağından) yapılır.
        Community clip URL'si asla render kaynağı olarak kullanılmaz.
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
            "-headers", f"User-Agent: {self._FFMPEG_UA}\r\nReferer: {self._FFMPEG_REFERER}\r\n",
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

            # FFmpeg'in Kick'ten 403/410 almasi da Cloudflare engeli olarak sayilmali
            error_lower = error_msg.lower()
            if any(code in error_lower for code in ["403", "410", "forbidden", "http error"]):
                self._cf_block_count += 1
                self._cf_last_block_time = time.monotonic()
                if not self._cf_alert_logged or self._cf_block_count % 10 == 0:
                    logger.critical(
                        "FFmpeg Kick HTTP hatasi (potansiyel Cloudflare): %s | "
                        "Impersonate: %s | Toplam: %d",
                        error_msg[:200], self._CF_IMPERSONATE, self._cf_block_count,
                    )
                    self._cf_alert_logged = True
                    self._send_cf_alert(
                        "FFmpeg Kick Engelleme",
                        f"FFmpeg Kick sunucusundan hata aldi: {error_msg[:200]}. "
                        f"Impersonate: {self._CF_IMPERSONATE} | Toplam: {self._cf_block_count}",
                    )

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
